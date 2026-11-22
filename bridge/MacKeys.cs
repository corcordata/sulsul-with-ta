// macOS 上的 F9（说话）和 F10（老板键）。
// 占全局快捷键用的是系统的 Carbon 接口（RegisterEventHotKey），它要在主线程上转一个事件循环，
// 所以跟切输入法一样：转发程序另开一份自己（SulSulBridge --hotkeys F9 F10），那一份什么都不干，只等按键，
// 按了就往外印一行 talk / boss；转发程序读到这一行再去办事。换键 = 把那一份关掉重开。
// 这两个键在小转发程序开着的时候一直被它占着；按下去时游戏不在最前面就什么都不做。
using System.Diagnostics;
using System.Runtime.InteropServices;

static class MacKeys
{
    const string Carbon = "/System/Library/Frameworks/Carbon.framework/Carbon";

    [StructLayout(LayoutKind.Sequential)]
    struct EventTypeSpec { public uint eventClass, eventKind; }

    [StructLayout(LayoutKind.Sequential)]
    struct EventHotKeyID { public uint signature, id; }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int Handler(IntPtr call, IntPtr theEvent, IntPtr userData);

    [DllImport(Carbon)] static extern IntPtr GetApplicationEventTarget();
    [DllImport(Carbon)] static extern int InstallEventHandler(IntPtr target, IntPtr handler, nuint count, EventTypeSpec[] types, IntPtr userData, out IntPtr handlerRef);
    [DllImport(Carbon)] static extern int RegisterEventHotKey(uint keyCode, uint modifiers, EventHotKeyID id, IntPtr target, uint options, out IntPtr hotKeyRef);
    [DllImport(Carbon)] static extern int GetEventParameter(IntPtr theEvent, uint name, uint type, IntPtr actualType, nuint size, IntPtr actualSize, out EventHotKeyID data);
    [DllImport(Carbon)] static extern void RunApplicationEventLoop();

    const uint ClassKeyboard = 0x6B657962;      // 'keyb'
    const uint HotKeyPressed = 5;
    const uint ParamDirectObject = 0x2D2D2D2D;  // '----'
    const uint TypeHotKeyID = 0x686B6964;       // 'hkid'

    static Handler? keepAlive;                  // 不留着的话会被回收，系统再来敲就崩了

    /// <summary>F1..F12 在 Mac 键盘上的键码；别的回 -1。</summary>
    static int MacCode(string name) => (name ?? "").Trim().ToUpperInvariant() switch
    {
        "F1" => 122, "F2" => 120, "F3" => 99, "F4" => 118, "F5" => 96, "F6" => 97,
        "F7" => 98, "F8" => 100, "F9" => 101, "F10" => 109, "F11" => 103, "F12" => 111,
        _ => -1,
    };

    /// <summary>那一份只等按键的进程：占住两个键，按了就印一行。永不返回。</summary>
    public static void RunChild(string talkKey, string bossKey, int parent)
    {
        // 转发程序没了（被关掉、崩了）这一份也要走，不然两个键会一直被占着
        new Thread(() =>
        {
            while (true)
            {
                Thread.Sleep(1500);
                try { if (Process.GetProcessById(parent).HasExited) Environment.Exit(0); }
                catch { Environment.Exit(0); }
            }
        }) { IsBackground = true }.Start();
        keepAlive = (_, theEvent, _) =>
        {
            if (GetEventParameter(theEvent, ParamDirectObject, TypeHotKeyID, IntPtr.Zero, 8, IntPtr.Zero, out var id) == 0)
            {
                Console.Out.WriteLine(id.id == 2 ? "boss" : "talk");
                Console.Out.Flush();
            }
            return 0;
        };
        IntPtr target = GetApplicationEventTarget();
        var types = new[] { new EventTypeSpec { eventClass = ClassKeyboard, eventKind = HotKeyPressed } };
        int installed = InstallEventHandler(target, Marshal.GetFunctionPointerForDelegate(keepAlive), 1, types, IntPtr.Zero, out _);
        if (installed != 0) { Console.Out.WriteLine($"error 装不上按键监听（{installed}）"); return; }
        int n = 0;
        foreach (string key in new[] { talkKey, bossKey })
        {
            n++;
            int code = MacCode(key);
            if (code < 0) continue;
            int status = RegisterEventHotKey((uint)code, 0, new EventHotKeyID { signature = 0x53554C53, id = (uint)n }, target, 0, out _);
            Console.Out.WriteLine(status == 0 ? $"ready {key}" : $"error 占不到 {key}（别的程序先占了，{status}）");
        }
        Console.Out.Flush();
        RunApplicationEventLoop();
    }

    /// <summary>转发程序里调这个：带起那一份、读它印的行；键换了或者它退了就重开。</summary>
    public static void Watch(Func<string> talkKey, Func<string> bossKey, Action talk, Action boss, Action<string> say)
    {
        var thread = new Thread(() =>
        {
            while (true)
            {
                string talkNow = talkKey(), bossNow = bossKey();
                Process? child = null;
                try
                {
                    var info = new ProcessStartInfo(Environment.ProcessPath!) { RedirectStandardOutput = true, UseShellExecute = false };
                    info.ArgumentList.Add("--hotkeys");
                    info.ArgumentList.Add(talkNow);
                    info.ArgumentList.Add(bossNow);
                    info.ArgumentList.Add(Environment.ProcessId.ToString());
                    child = Process.Start(info);
                    if (child is null) { Thread.Sleep(5000); continue; }
                    var mine = child;
                    var reader = new Thread(() =>
                    {
                        try
                        {
                            string? line;
                            while ((line = mine.StandardOutput.ReadLine()) != null)
                            {
                                if (line == "talk") talk();
                                else if (line == "boss") boss();
                                else if (line.StartsWith("error ", StringComparison.Ordinal)) say(line[6..]);
                            }
                        }
                        catch { }
                    }) { IsBackground = true };
                    reader.Start();
                    while (!child.HasExited && talkKey() == talkNow && bossKey() == bossNow) Thread.Sleep(400);
                }
                catch (Exception ex) { say($"快捷键没开起来：{ex.Message}"); Thread.Sleep(10000); }
                finally
                {
                    try { if (child is { HasExited: false }) child.Kill(); } catch { }
                    child?.Dispose();
                }
                Thread.Sleep(300);
            }
        }) { IsBackground = true, Name = "SulSulMacKeys" };
        thread.Start();
    }
}
