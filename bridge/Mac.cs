// macOS 上的那几样：游戏装在哪、游戏是不是在最前面、替 TA 按一下截图键。
// 全部走系统自带的 osascript（System Events），不碰原生接口：
//   看哪个程序在最前面 → 第一次会问「允许控制 System Events 吗」（隐私与安全性 → 自动化）
//   按键               → 要在 隐私与安全性 → 辅助功能 里把打开这个程序的那个「终端」勾上
// Mac 版没有的：F9 / F10 快捷键、自动切输入法。跟 TA 说话用游戏里的输入条（Cmd+Shift+C，输入 ta）。
using System.Diagnostics;

static class Mac
{
    static (int code, string output) Osa(string script, int timeoutMs = 5000)
    {
        try
        {
            var info = new ProcessStartInfo("/usr/bin/osascript")
            {
                RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false,
            };
            info.ArgumentList.Add("-e");
            info.ArgumentList.Add(script);
            using var process = Process.Start(info);
            if (process is null) return (-1, "");
            string output = process.StandardOutput.ReadToEnd();
            string error = process.StandardError.ReadToEnd();
            if (!process.WaitForExit(timeoutMs))
            {
                try { process.Kill(); } catch { }
                return (-1, "等太久了");
            }
            return (process.ExitCode, (process.ExitCode == 0 ? output : error).Trim());
        }
        catch (Exception ex) { return (-1, ex.Message); }
    }

    static bool IsGame(string name) => name.Contains("Sims", StringComparison.OrdinalIgnoreCase);

    /// <summary>替 TA 按一下游戏的截图键（C）。只在游戏是最前面的程序时按。成了回 null，不成回原因。</summary>
    public static string? PressC()
    {
        var (code, front) = Osa("tell application \"System Events\" to get name of first application process whose frontmost is true");
        if (code != 0)
            return "这台 Mac 没让转发程序看哪个程序在最前面。请她打开 系统设置 → 隐私与安全性 → 自动化，允许「终端」控制 System Events。";
        if (!IsGame(front))
            return "游戏不在最前面（她可能切到别的窗口了），等她回到游戏里再拍。";
        (code, _) = Osa("tell application \"System Events\" to keystroke \"c\"");
        if (code != 0)
            return "这台 Mac 没让转发程序按键。请她打开 系统设置 → 隐私与安全性 → 辅助功能，把「终端」勾上，再重开转发程序。";
        return null;
    }

    /// <summary>游戏装在哪：回 …/The Sims 4.app/Contents（字库在它下面某一层）。找不到回空。</summary>
    public static string GameDir()
    {
        try
        {
            foreach (var process in Process.GetProcesses())
            {
                try
                {
                    if (!IsGame(process.ProcessName)) continue;
                    string exe = process.MainModule?.FileName ?? "";
                    int at = exe.IndexOf(".app/Contents/", StringComparison.OrdinalIgnoreCase);
                    if (at < 0) continue;
                    string root = exe[..(at + ".app/Contents".Length)];
                    if (Directory.Exists(root)) return root;
                }
                catch { }
            }
        }
        catch { }
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        foreach (string app in new[]
        {
            "/Applications/The Sims 4.app",
            Path.Combine(home, "Applications/The Sims 4.app"),
            Path.Combine(home, "Library/Application Support/Steam/steamapps/common/The Sims 4/The Sims 4.app"),
        })
        {
            string root = Path.Combine(app, "Contents");
            if (Directory.Exists(root)) return root;
        }
        return "";
    }
}
