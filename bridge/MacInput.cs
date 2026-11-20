// macOS 上切输入法：输入框弹出来切到中文，关掉切回原来的。
// 用的是系统的「文本输入源」接口（Carbon 里的 TIS*）。苹果要求这些接口在主线程上调，
// 所以不在转发程序里直接调，而是让它另开一份自己（SulSulBridge --ime zh|en|show），在那一份的主线程上做完就退出。
// 切之前是哪个输入源记在 SulSulBridge.ime 里，这样切回去的是玩家原来用的那个，不是随便挑的。
using System.Runtime.InteropServices;

static class MacInput
{
    const string Carbon = "/System/Library/Frameworks/Carbon.framework/Carbon";
    const string CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation";

    [StructLayout(LayoutKind.Sequential)]
    struct CFRange { public nint location, length; }

    [DllImport(Carbon)] static extern IntPtr TISCopyCurrentKeyboardInputSource();
    [DllImport(Carbon)] static extern IntPtr TISCreateInputSourceList(IntPtr properties, byte includeAllInstalled);
    [DllImport(Carbon)] static extern int TISSelectInputSource(IntPtr source);
    [DllImport(Carbon)] static extern IntPtr TISGetInputSourceProperty(IntPtr source, IntPtr key);
    [DllImport(CF)] static extern nint CFArrayGetCount(IntPtr array);
    [DllImport(CF)] static extern IntPtr CFArrayGetValueAtIndex(IntPtr array, nint index);
    [DllImport(CF)] static extern nint CFStringGetLength(IntPtr text);
    [DllImport(CF, CharSet = CharSet.Unicode)] static extern void CFStringGetCharacters(IntPtr text, CFRange range, [Out] char[] buffer);   // 系统给的是 UTF-16
    [DllImport(CF)] static extern byte CFBooleanGetValue(IntPtr value);
    [DllImport(CF)] static extern void CFRelease(IntPtr thing);

    record Source(IntPtr Handle, string Id, string Language, string Type, bool Selectable);

    static IntPtr Key(IntPtr library, string name) => Marshal.ReadIntPtr(NativeLibrary.GetExport(library, name));

    static string Text(IntPtr cfString)
    {
        if (cfString == IntPtr.Zero) return "";
        int length = (int)CFStringGetLength(cfString);
        if (length <= 0 || length > 1024) return "";
        var buffer = new char[length];
        CFStringGetCharacters(cfString, new CFRange { location = 0, length = length }, buffer);
        return new string(buffer);
    }

    static Source Read(IntPtr handle, IntPtr idKey, IntPtr languagesKey, IntPtr typeKey, IntPtr selectableKey)
    {
        string language = "";
        IntPtr languages = TISGetInputSourceProperty(handle, languagesKey);
        if (languages != IntPtr.Zero && CFArrayGetCount(languages) > 0) language = Text(CFArrayGetValueAtIndex(languages, 0));
        IntPtr selectable = TISGetInputSourceProperty(handle, selectableKey);
        return new Source(handle, Text(TISGetInputSourceProperty(handle, idKey)), language,
                          Text(TISGetInputSourceProperty(handle, typeKey)),
                          selectable != IntPtr.Zero && CFBooleanGetValue(selectable) != 0);
    }

    static bool IsChinese(Source s) => s.Language.StartsWith("zh", StringComparison.OrdinalIgnoreCase);

    // 能当「英文」用的：普通键盘布局（ABC、美国、英国……），不是输入法
    static bool IsPlain(Source s) => s.Type == "TISTypeKeyboardLayout" && !IsChinese(s);

    /// <summary>mode：zh 切到中文，en 切回原来的，show 只看不动。回一句给人看的话。</summary>
    public static string Run(string mode, string memoryPath)
    {
        IntPtr list = IntPtr.Zero, now = IntPtr.Zero;
        try
        {
            IntPtr library = NativeLibrary.Load(Carbon);
            IntPtr idKey = Key(library, "kTISPropertyInputSourceID"), languagesKey = Key(library, "kTISPropertyInputSourceLanguages"),
                   typeKey = Key(library, "kTISPropertyInputSourceType"), selectableKey = Key(library, "kTISPropertyInputSourceIsSelectCapable");
            list = TISCreateInputSourceList(IntPtr.Zero, 0);      // 只要已经启用的
            var sources = new List<Source>();
            for (nint i = 0, n = list == IntPtr.Zero ? 0 : CFArrayGetCount(list); i < n; i++)
            {
                var source = Read(CFArrayGetValueAtIndex(list, i), idKey, languagesKey, typeKey, selectableKey);
                if (source.Selectable && source.Id.Length > 0 && source.Type.StartsWith("TISTypeKeyboard", StringComparison.Ordinal)) sources.Add(source);
            }
            now = TISCopyCurrentKeyboardInputSource();
            var current = Read(now, idKey, languagesKey, typeKey, selectableKey);
            if (mode == "show")
                return $"现在是 {current.Id}。启用的：{string.Join("、", sources.Select(s => s.Id + (IsChinese(s) ? "（中文）" : IsPlain(s) ? "（英文键盘）" : "")))}";

            string remembered = "";
            try { remembered = File.Exists(memoryPath) ? File.ReadAllText(memoryPath).Trim() : ""; } catch { }
            Source? Find(string id) => sources.FirstOrDefault(s => s.Id == id);
            Source? target;
            if (mode == "zh")
            {
                if (IsChinese(current)) return $"本来就是中文（{current.Id}），没动。";
                // 记得上次从哪个中文输入法切走的就回那个；不记得就用第一个中文的
                target = Find(remembered) is { } last && IsChinese(last) ? last : sources.FirstOrDefault(IsChinese);
                if (target is null) return "这台 Mac 没启用中文输入法，没动。";
            }
            else
            {
                if (!IsChinese(current)) return $"本来就不是中文（{current.Id}），没动。";
                target = Find(remembered) is { } before && !IsChinese(before) ? before : sources.FirstOrDefault(IsPlain);
                if (target is null) return "这台 Mac 没启用英文键盘（比如 ABC），切不回去。";
            }
            try { File.WriteAllText(memoryPath, current.Id); } catch { }     // 记下切之前的，下次反方向时回它
            int status = TISSelectInputSource(target.Handle);
            if (status != 0) return $"系统没让切（{status}）。";
            return $"{current.Id} → {target.Id}";
        }
        catch (Exception ex) { return $"切输入法的时候出错了：{ex.Message}"; }
        finally
        {
            if (now != IntPtr.Zero) CFRelease(now);
            if (list != IntPtr.Zero) CFRelease(list);
        }
    }

    /// <summary>转发程序里调这个：另开一份自己去切，等它回话。</summary>
    public static string Switch(bool chinese)
    {
        try
        {
            string? self = Environment.ProcessPath;
            if (string.IsNullOrEmpty(self)) return "找不到自己在哪，没切。";
            var info = new System.Diagnostics.ProcessStartInfo(self) { RedirectStandardOutput = true, UseShellExecute = false };
            info.ArgumentList.Add("--ime");
            info.ArgumentList.Add(chinese ? "zh" : "en");
            using var process = System.Diagnostics.Process.Start(info);
            if (process is null) return "没开起来，没切。";
            string output = process.StandardOutput.ReadToEnd().Trim();
            if (!process.WaitForExit(4000)) { try { process.Kill(); } catch { } return "等太久了，没切成。"; }
            return output.Length > 0 ? output : "没回话。";
        }
        catch (Exception ex) { return $"切输入法的时候出错了：{ex.Message}"; }
    }
}
