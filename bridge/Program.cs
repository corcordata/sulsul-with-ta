// SimsLinkBridge：玩家 Windows 上的小转发程序。
// Sims 4 里的 Python 没有 ssl，连不了 https。游戏里的 mod 只敲本机这个端口，
// 这里带上钥匙把它转给你自己的服务器，再把回话原样带回去。只转 /sims/mod/ 开头的路径。
//
// /local/ 开头的请求不转发，由这里自己处理：
//   拍照：AI 说「拍一张」→ 替 TA 按游戏的截图键（C）→ 等游戏把图存进截图文件夹 → 传给服务器。
//   玩家的截图：ta pic 发最新的几张；ta pics on 之后新截的自动发。
//   说话快捷键（默认 F9）：游戏在最前面时按一下，mod 就弹出输入框，不用开控制台。
//   输入法：输入框弹出来时切到中文，关掉时切回英文（中文输入法开着的时候 WASD 会被它吃掉）。
//   老板键（默认 F10）：游戏窗口立刻缩下去、电脑静音，再请 mod 把游戏暂停。
//     缩窗口和静音是这里直接跟 Windows 说的，游戏卡死了也照样管用。回到游戏窗口时自动取消静音。
//   查名字：动作、状态在游戏里只是一个号码，字在游戏的字库文件里（Strings.cs）。
using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

Console.OutputEncoding = Encoding.UTF8;
try { Console.Title = "SimsLinkBridge · 开着别关"; } catch { }

string dir = AppContext.BaseDirectory;
string cfgPath = Path.Combine(dir, "SimsLinkBridge.cfg");
string relay = "", token = "";
int port = 47931;
try
{
    using var doc = JsonDocument.Parse(File.ReadAllText(cfgPath));
    var root = doc.RootElement;
    relay = (root.TryGetProperty("server", out var r) ? r.GetString() ?? "" : "").TrimEnd('/');
    token = root.TryGetProperty("token", out var t) ? t.GetString() ?? "" : "";
    if (root.TryGetProperty("port", out var p) && p.TryGetInt32(out var pv)) port = pv;
}
catch (Exception ex)
{
    Fail($"读不了 SimsLinkBridge.cfg（要跟这个程序放在同一个文件夹里）：{ex.Message}");
    return;
}
if (relay.Length == 0 || token.Length == 0)
{
    Fail("SimsLinkBridge.cfg 里的 server 或 token 是空的。用记事本打开它，把你服务器的地址和钥匙填进去。");
    return;
}

var http = new HttpClient { Timeout = TimeSpan.FromSeconds(40) };
http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);

var listener = new TcpListener(IPAddress.Loopback, port);
try { listener.Start(); }
catch (SocketException)
{
    Fail($"端口 {port} 被占了。是不是已经开着一个 SimsLinkBridge？关掉多的那个就行。");
    return;
}

DateTime lastGame = DateTime.MinValue;
bool relayDown = false;
object gate = new();

// ── 拍照用的状态 ──
string simsDir = "";                                // …\The Sims 4 那一层，mod 告诉我们
// 截图文件夹的名字跟着游戏语言走（英文 Screenshots，中文「游戏截图」……），所以不认名字：
// 这一层下面除了这几个肯定不是截图的文件夹，哪个里面冒出新的 png / jpg 就算哪个。
var notShots = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
{
    "Mods", "saves", "Tray", "cachestr", "onlinethumbnailcache", "Content", "ConfigOverride",
    "Custom Music", "ReticulatedSplines", "Recorded Videos",
};
var known = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
var sizes = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
TaskCompletionSource<string>? waitingShot = null;   // AI 按了快门，等这张图出现
bool autoOn = false;                                // 玩家新截的图要不要自动发给 AI
var autoQueue = new List<string>();
DateTime autoLast = DateTime.MinValue;
var shootLock = new SemaphoreSlim(1, 1);

// ── 说话快捷键 ──
string keyPath = Path.Combine(dir, "SimsLinkBridge.key");   // 只存一个键名，跟装着钥匙的 cfg 分开
string hotkey = "F9";
try { if (File.Exists(keyPath) && Win.KeyCode(File.ReadAllText(keyPath).Trim()) != 0) hotkey = File.ReadAllText(keyPath).Trim().ToUpperInvariant(); } catch { }
var keySignal = new SemaphoreSlim(0, 1);
DateTime keyAt = DateTime.MinValue;
int imeTurn = 0;                                     // 第几次切输入法：补切的时候用来认「还是不是这一次」
string keyKind = "talk";                             // 刚按的是哪个：talk=说话，boss=老板键
string bossPath = Path.Combine(dir, "SimsLinkBridge.boss");
string bossKey = "F10";
try { if (File.Exists(bossPath) && Win.KeyCode(File.ReadAllText(bossPath).Trim()) != 0) bossKey = File.ReadAllText(bossPath).Trim().ToUpperInvariant(); } catch { }
bool testing = Environment.GetEnvironmentVariable("SIMSLINK_FAKE_SHOT") is { Length: > 0 };

Strings.Init(dir, Say);
Say("SimsLinkBridge 1.0.0 开着了。玩 Sims 的时候让这个窗口一直开着，最小化就行。");
Say($"想跟 TA 说话：在游戏里按 {hotkey}。老板键：{bossKey}（游戏立刻缩下去 + 静音）。换键：游戏控制台打 ta key F9 / ta boss F10 这样。");
await Probe();
Say("等游戏来敲门……（进到存档里才会敲）");
_ = Task.Run(WatchScreenshots);
if (OperatingSystem.IsWindows()) Win.WatchHotkey(() => hotkey, () => bossKey, () => Pressed("talk"), Boss, Say);

while (true)
{
    TcpClient client;
    try { client = await listener.AcceptTcpClientAsync(); }
    catch { continue; }
    _ = Task.Run(() => Handle(client));
}

async Task Probe()
{
    try
    {
        using var res = await Post("/sims/mod/sync", Encoding.UTF8.GetBytes("{\"probe\":true}"), "application/json");
        if (res.IsSuccessStatusCode) Say("服务器连得上 ✓");
        else if ((int)res.StatusCode is 401 or 403) Say("服务器不认这把钥匙：SimsLinkBridge.cfg 里的 token 要填服务器上的 MOD_TOKEN。");
        else Say($"服务器回了 {(int)res.StatusCode}，先开着，游戏来了再试。");
    }
    catch (Exception ex)
    {
        Say($"现在连不上服务器（{Short(ex)}）。检查一下网络，先开着，会自己重试。");
    }
}

Task<HttpResponseMessage> Post(string path, byte[] body, string contentType)
{
    var req = new HttpRequestMessage(HttpMethod.Post, relay + path) { Content = new ByteArrayContent(body) };
    req.Content.Headers.ContentType = new MediaTypeHeaderValue(contentType);
    return http.SendAsync(req);
}

async Task Handle(TcpClient client)
{
    using (client)
    {
        try
        {
            client.NoDelay = true;
            var stream = client.GetStream();
            stream.ReadTimeout = 15000;
            var (path, body) = await ReadRequest(stream);
            if (path is null) { await Reply(stream, 400, "{\"detail\":\"bad request\"}"u8.ToArray()); return; }
            if (path.StartsWith("/local/", StringComparison.Ordinal))
            {
                string answer;
                try { answer = await Local(path, body); }
                catch (Exception ex) { answer = Answer(false, $"转发程序出错了：{Short(ex)}"); }
                await Reply(stream, 200, Encoding.UTF8.GetBytes(answer));
                return;
            }
            if (!path.StartsWith("/sims/mod/", StringComparison.Ordinal))
            {
                await Reply(stream, 404, "{\"detail\":\"not forwarded\"}"u8.ToArray());
                return;
            }
            lock (gate)
            {
                if ((DateTime.Now - lastGame).TotalSeconds > 40) Say("游戏连上了 ✓");
                lastGame = DateTime.Now;
            }
            try
            {
                using var res = await Post(path, body, "application/json");
                var bytes = await res.Content.ReadAsByteArrayAsync();
                lock (gate)
                {
                    if (relayDown && res.IsSuccessStatusCode) { relayDown = false; Say("服务器又连上了 ✓"); }
                    if (!res.IsSuccessStatusCode && !relayDown) { relayDown = true; Say($"服务器回了 {(int)res.StatusCode}，会一直重试。"); }
                }
                await Reply(stream, (int)res.StatusCode, bytes);
            }
            catch (Exception ex)
            {
                lock (gate)
                {
                    if (!relayDown) { relayDown = true; Say($"连不上服务器（{Short(ex)}），会一直重试。"); }
                }
                await Reply(stream, 502, Encoding.UTF8.GetBytes("{\"detail\":\"relay unreachable\"}"));
            }
        }
        catch { }
    }
}

// ───────────────────────── 拍照 ─────────────────────────

async Task<string> Local(string path, byte[] body)
{
    using var doc = JsonDocument.Parse(body.Length == 0 ? "{}"u8.ToArray() : body);
    var root = doc.RootElement;
    string givenDir = root.TryGetProperty("dir", out var d) ? d.GetString() ?? "" : "";
    if (givenDir.Length > 0) SetSimsDir(givenDir);
    string caption = root.TryGetProperty("caption", out var c) ? c.GetString() ?? "" : "";

    switch (path)
    {
        case "/local/hello":
            return Answer(true, "1.0.0");
        case "/local/names":
            var keys = new List<uint>();
            if (root.TryGetProperty("keys", out var ks) && ks.ValueKind == JsonValueKind.Array)
                foreach (var item in ks.EnumerateArray())
                    if (item.TryGetUInt32(out uint key)) keys.Add(key);
            bool namesReady = false;
            var names = await Task.Run(() => Strings.Lookup(keys.Take(2000), 9000, out namesReady));
            using (var ms = new MemoryStream())
            {
                using (var w = new Utf8JsonWriter(ms))
                {
                    w.WriteStartObject();
                    w.WriteBoolean("ok", true);
                    w.WriteString("text", "");
                    w.WriteBoolean("ready", namesReady);
                    w.WriteStartObject("names");
                    foreach (var pair in names) w.WriteString(pair.Key.ToString(), pair.Value);
                    w.WriteEndObject();
                    w.WriteEndObject();
                }
                return Encoding.UTF8.GetString(ms.ToArray());
            }
        case "/local/wait":
            // mod 在这里等：玩家按了说话快捷键就回 talk，25 秒没按就空手回去，mod 再来等
            bool pressed = await keySignal.WaitAsync(TimeSpan.FromSeconds(testing ? 3 : 25));
            return Answer(true, pressed && (DateTime.Now - keyAt).TotalSeconds < 5 ? keyKind : "");
        case "/local/press" when testing:
            if (root.TryGetProperty("which", out var pw) && pw.GetString() == "boss") Boss(); else Pressed("talk");
            return Answer(true, "pressed");
        case "/local/key":
            string wanted = (root.TryGetProperty("key", out var k) ? k.GetString() ?? "" : "").Trim().ToUpperInvariant();
            bool forBoss = root.TryGetProperty("which", out var kw) && kw.GetString() == "boss";
            if (wanted.Length == 0) return Answer(true, $"说话快捷键是 {hotkey}，老板键是 {bossKey}。");
            if (Win.KeyCode(wanted) == 0 || wanted == "F12") return Answer(false, "只认 F1 到 F11（F12 被 Windows 自己占着）。比如 ta key F9、ta boss F10。");
            if (wanted == (forBoss ? hotkey : bossKey)) return Answer(false, $"{wanted} 已经是{(forBoss ? "说话快捷键" : "老板键")}了，两个不能用同一个键。");
            if (forBoss)
            {
                bossKey = wanted;
                try { File.WriteAllText(bossPath, wanted); } catch { }
                Say($"老板键换成 {bossKey} 了。");
                return Answer(true, $"换好了：老板键是 {bossKey}。");
            }
            hotkey = wanted;
            try { File.WriteAllText(keyPath, wanted); } catch { }
            Say($"说话快捷键换成 {hotkey} 了。");
            return Answer(true, $"换好了：以后在游戏里按 {hotkey} 跟 TA 说话。");
        case "/local/ime":
            bool chinese = root.TryGetProperty("on", out var imeOn) && imeOn.ValueKind == JsonValueKind.True;
            string imeNote = OperatingSystem.IsWindows() ? Win.Ime(chinese) : "（不是 Windows，假装切了）";
            int myTurn = Interlocked.Increment(ref imeTurn);
            if (OperatingSystem.IsWindows())
            {
                // 输入框弹出 / 收起的那一下，游戏会把输入法的状态冲掉（真机上关框之后没切回英文）。
                // 所以过一会儿再补两次；中间玩家要是又开了一次框，旧的这几次就作废。
                _ = Task.Run(async () =>
                {
                    string last = "";
                    foreach (int wait in new[] { 350, 700 })
                    {
                        await Task.Delay(wait);
                        if (Volatile.Read(ref imeTurn) != myTurn) return;
                        last = Win.Ime(chinese);
                    }
                    Say((chinese ? "　　　补切中文：" : "　　　补切英文：") + last);
                });
            }
            Say((chinese ? "输入框开了，输入法 → 中文：" : "输入框关了，输入法 → 英文：") + imeNote);
            return Answer(true, imeNote);
        case "/local/shoot":
            long shot = root.TryGetProperty("shot", out var s) && s.TryGetInt64(out var sv) ? sv : 0;
            return await Shoot(shot, caption);
        case "/local/send":
            int count = root.TryGetProperty("count", out var n) && n.TryGetInt32(out var nv) ? Math.Clamp(nv, 1, 6) : 1;
            return await SendLatest(count, caption);
        case "/local/auto":
            bool on = root.TryGetProperty("on", out var o) && o.ValueKind == JsonValueKind.True;
            lock (gate)
            {
                autoOn = on;
                autoQueue.Clear();
            }
            Say(on ? "自动分享开了：你新截的图会自己发给 TA。" : "自动分享关了。");
            return Answer(true, on
                ? "开了：从现在起你按 C 截的图会自己发给 TA。关掉用 ta pics off。"
                : "关了：截图只留在你电脑上。");
        default:
            return Answer(false, "这个版本的转发程序不认识这个请求");
    }
}

void Pressed(string kind)
{
    keyKind = kind;
    keyAt = DateTime.Now;
    try { if (keySignal.CurrentCount == 0) keySignal.Release(); } catch (SemaphoreFullException) { }
}

void Boss()
{
    // 先做不靠游戏的两样（缩窗口、静音），再请 mod 暂停——游戏卡死的时候最后那步做不成，前两样照样成
    string done = OperatingSystem.IsWindows() ? Win.Hide() : "（不是 Windows，假装藏了）";
    Say("老板键：" + done);
    Pressed("boss");
}

void SetSimsDir(string path)
{
    lock (gate)
    {
        if (string.Equals(path, simsDir, StringComparison.OrdinalIgnoreCase)) return;
        simsDir = path;
        Strings.Prepare(path);
        known.Clear();
        sizes.Clear();
        foreach (var file in ListShots()) known.Add(file);      // 已经在那儿的旧图不算新的
        if (!Directory.Exists(simsDir)) Say($"游戏的文件夹没找到：{simsDir}");
        else
        {
            var withPictures = ShotDirs().Where(HasPictures).Select(Path.GetFileName).ToList();
            Say($"游戏文件夹：{simsDir}");
            Say(withPictures.Count > 0
                ? $"截图在这里面找：{string.Join("、", withPictures)}"
                : "里面还没看到截图，你按 C 截第一张之后就认得了。");
        }
    }
}

List<string> ShotDirs()
{
    try
    {
        if (simsDir.Length == 0 || !Directory.Exists(simsDir)) return [];
        return Directory.EnumerateDirectories(simsDir)
            .Where(d => !notShots.Contains(Path.GetFileName(d)))
            .ToList();
    }
    catch { return []; }
}

static bool IsPicture(string f) =>
    f.EndsWith(".png", StringComparison.OrdinalIgnoreCase) || f.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase);

static bool HasPictures(string folder)
{
    try { return Directory.EnumerateFiles(folder).Any(IsPicture); } catch { return false; }
}

List<string> ListShots()
{
    var all = new List<string>();
    foreach (var folder in ShotDirs())
    {
        try { all.AddRange(Directory.EnumerateFiles(folder).Where(IsPicture)); } catch { }
    }
    return all;
}

async Task WatchScreenshots()
{
    while (true)
    {
        await Task.Delay(400);
        try
        {
            List<string> ready = [];
            lock (gate)
            {
                foreach (var file in ListShots())
                {
                    if (known.Contains(file)) continue;
                    long size;
                    try { size = new FileInfo(file).Length; } catch { continue; }
                    // 游戏还在往里写的时候大小会变；连着两次一样大才算写完
                    if (size > 0 && sizes.TryGetValue(file, out var before) && before == size)
                    {
                        known.Add(file);
                        sizes.Remove(file);
                        ready.Add(file);
                    }
                    else sizes[file] = size;
                }
                foreach (var file in ready)
                {
                    if (waitingShot is not null) { waitingShot.TrySetResult(file); waitingShot = null; }
                    else if (autoOn) { autoQueue.Add(file); autoLast = DateTime.Now; }
                }
            }
            List<string> flush = [];
            lock (gate)
            {
                if (autoQueue.Count > 0 && (DateTime.Now - autoLast).TotalSeconds >= 3)
                {
                    flush = autoQueue.TakeLast(6).ToList();
                    autoQueue.Clear();
                }
            }
            if (flush.Count > 0)
            {
                var result = await UploadHers(flush, "");
                Say(result.ok ? $"自动把 {flush.Count} 张截图发给 TA 了。" : $"自动传截图没成：{result.text}");
            }
        }
        catch { }
    }
}

async Task<string> Shoot(long shot, string caption)
{
    if (simsDir.Length == 0 || !Directory.Exists(simsDir))
        return Answer(false, $"找不到游戏的文件夹（{simsDir}），拍不了。");
    if (!await shootLock.WaitAsync(0))
        return Answer(false, "上一张还在拍，等一下。");
    try
    {
        var waiter = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (gate) { waitingShot = waiter; }
        string? problem = PressShutter();
        if (problem is not null)
        {
            lock (gate) { waitingShot = null; }
            return Answer(false, problem);
        }
        var done = await Task.WhenAny(waiter.Task, Task.Delay(7000));
        if (done != waiter.Task)
        {
            lock (gate) { waitingShot = null; }
            return Answer(false, "按了快门，但游戏没存出新截图。可能她的输入法在中文状态，或者正在打字、开着菜单。过一会儿再拍。");
        }
        string file = await waiter.Task;
        var bytes = await ReadWhenFree(file);
        using var res = await Post($"/sims/mod/photo?by=him&shot={shot}&caption={Uri.EscapeDataString(caption)}", bytes, Mime(file));
        if (!res.IsSuccessStatusCode)
            return Answer(false, $"拍到了，但服务器没收下（{(int)res.StatusCode}）。");
        Say("TA 拍了一张照片。");
        return Answer(true, "拍到了。");
    }
    finally { shootLock.Release(); }
}

string? PressShutter()
{
    // 测试用：没有游戏的时候，把一张现成的图放进截图文件夹，假装游戏刚存出来
    string? fake = Environment.GetEnvironmentVariable("SIMSLINK_FAKE_SHOT");
    if (!string.IsNullOrEmpty(fake))
    {
        string into = ShotDirs().FirstOrDefault(HasPictures) ?? ShotDirs().First();
        File.Copy(fake, Path.Combine(into, $"fake-{DateTime.Now.Ticks}{Path.GetExtension(fake)}"));
        return null;
    }
    if (!OperatingSystem.IsWindows()) return "转发程序不在 Windows 上，按不了截图键。";
    return Win.PressC();
}

async Task<string> SendLatest(int count, string caption)
{
    var files = ListShots();
    if (simsDir.Length == 0 || !Directory.Exists(simsDir))
        return Answer(false, $"找不到游戏的文件夹（{simsDir}）。");
    if (files.Count == 0) return Answer(false, $"在 {simsDir} 下面没找到截图。在游戏里按 C 截一张再发。");
    var latest = files.OrderByDescending(f => File.GetLastWriteTimeUtc(f)).Take(count).Reverse().ToList();
    var result = await UploadHers(latest, caption);
    if (result.ok) Say($"发了 {latest.Count} 张截图给 TA。");
    return Answer(result.ok, result.ok ? $"发给 TA 了，{latest.Count} 张。" : result.text);
}

async Task<(bool ok, string text)> UploadHers(List<string> files, string caption)
{
    for (int i = 0; i < files.Count; i++)
    {
        bool last = i == files.Count - 1;
        var bytes = await ReadWhenFree(files[i]);
        string query = $"/sims/mod/photo?by=her&hold={(last ? "0" : "1")}&caption={Uri.EscapeDataString(last ? caption : "")}";
        try
        {
            using var res = await Post(query, bytes, Mime(files[i]));
            if (!res.IsSuccessStatusCode) return (false, $"服务器没收下（{(int)res.StatusCode}）。");
        }
        catch (Exception ex) { return (false, $"传不上去：{Short(ex)}"); }
    }
    return (true, "");
}

static async Task<byte[]> ReadWhenFree(string file)
{
    for (int attempt = 0; ; attempt++)
    {
        try { return await File.ReadAllBytesAsync(file); }
        catch (IOException) when (attempt < 10) { await Task.Delay(200); }
    }
}

static string Mime(string file) => file.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ? "image/png" : "image/jpeg";

static string Answer(bool ok, string text)
{
    using var ms = new MemoryStream();
    using (var w = new Utf8JsonWriter(ms))
    {
        w.WriteStartObject();
        w.WriteBoolean("ok", ok);
        w.WriteString("text", text);
        w.WriteEndObject();
    }
    return Encoding.UTF8.GetString(ms.ToArray());
}

// ───────────────────────── 收发 ─────────────────────────

static async Task<(string? path, byte[] body)> ReadRequest(NetworkStream stream)
{
    var buf = new byte[65536];
    int have = 0, headerEnd = -1;
    while (headerEnd < 0)
    {
        if (have == buf.Length) return (null, []);
        int n = await stream.ReadAsync(buf.AsMemory(have, buf.Length - have));
        if (n <= 0) return (null, []);
        have += n;
        headerEnd = IndexOfHeaderEnd(buf, have);
    }
    string head = Encoding.ASCII.GetString(buf, 0, headerEnd);
    var lines = head.Split("\r\n");
    var first = lines[0].Split(' ');
    if (first.Length < 2 || first[0] != "POST") return (null, []);
    int length = 0;
    foreach (var line in lines.Skip(1))
    {
        int colon = line.IndexOf(':');
        if (colon > 0 && line[..colon].Trim().Equals("Content-Length", StringComparison.OrdinalIgnoreCase))
            int.TryParse(line[(colon + 1)..].Trim(), out length);
    }
    if (length < 0 || length > 2_000_000) return (null, []);
    var body = new byte[length];
    int start = headerEnd + 4;
    int got = Math.Min(length, have - start);
    if (got > 0) Buffer.BlockCopy(buf, start, body, 0, got);
    while (got < length)
    {
        int n = await stream.ReadAsync(body.AsMemory(got, length - got));
        if (n <= 0) return (null, []);
        got += n;
    }
    return (first[1], body);
}

static int IndexOfHeaderEnd(byte[] buf, int have)
{
    for (int i = 0; i + 3 < have; i++)
        if (buf[i] == 13 && buf[i + 1] == 10 && buf[i + 2] == 13 && buf[i + 3] == 10) return i;
    return -1;
}

static async Task Reply(NetworkStream stream, int status, byte[] body)
{
    string reason = status == 200 ? "OK" : "Error";
    var head = Encoding.ASCII.GetBytes(
        $"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {body.Length}\r\nConnection: close\r\n\r\n");
    await stream.WriteAsync(head);
    await stream.WriteAsync(body);
    await stream.FlushAsync();
}

static string Short(Exception ex) => (ex.InnerException ?? ex).Message.Split('\n')[0];

static void Say(string text) => Console.WriteLine($"[{DateTime.Now:HH:mm:ss}] {text}");

static void Fail(string text)
{
    Say(text);
    Console.WriteLine("按回车关闭。");
    try { Console.ReadLine(); } catch { }
}

/// <summary>Windows 上替 AI 按一下游戏的截图键。只在游戏是最前面的窗口时按，免得按到别的程序里。</summary>
static class Win
{
    [StructLayout(LayoutKind.Sequential)]
    struct MOUSEINPUT { public int dx, dy; public uint mouseData, dwFlags, time; public IntPtr dwExtraInfo; }

    [StructLayout(LayoutKind.Sequential)]
    struct KEYBDINPUT { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr dwExtraInfo; }

    [StructLayout(LayoutKind.Explicit)]
    struct InputUnion { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }

    [StructLayout(LayoutKind.Sequential)]
    struct INPUT { public uint type; public InputUnion U; }

    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint count, INPUT[] inputs, int size);

    const uint INPUT_KEYBOARD = 1, KEYEVENTF_KEYUP = 0x0002, KEYEVENTF_SCANCODE = 0x0008;
    const ushort SCAN_C = 0x2E;

    /// <summary>游戏的窗口，只在它是最前面那个时才给；不是就给 0。</summary>
    static IntPtr GameWindow()
    {
        try
        {
            IntPtr window = GetForegroundWindow();
            if (window == IntPtr.Zero) return IntPtr.Zero;
            GetWindowThreadProcessId(window, out uint pid);
            string name = pid == 0 ? "" : Process.GetProcessById((int)pid).ProcessName;
            return name.StartsWith("TS4", StringComparison.OrdinalIgnoreCase) ? window : IntPtr.Zero;
        }
        catch { return IntPtr.Zero; }
    }

    // ── 说话快捷键 ──
    [StructLayout(LayoutKind.Sequential)]
    struct MSG { public IntPtr hwnd; public uint message; public IntPtr wParam, lParam; public uint time; public int x, y; }

    [DllImport("user32.dll", SetLastError = true)] static extern bool RegisterHotKey(IntPtr hWnd, int id, uint modifiers, uint vk);
    [DllImport("user32.dll")] static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")] static extern bool PeekMessage(out MSG msg, IntPtr hWnd, uint min, uint max, uint remove);

    const uint WM_HOTKEY = 0x0312, MOD_NOREPEAT = 0x4000, PM_REMOVE = 1;

    /// <summary>F1..F12 → 虚拟键码；别的一律 0。</summary>
    public static uint KeyCode(string name)
    {
        name = (name ?? "").Trim().ToUpperInvariant();
        return name.Length >= 2 && name[0] == 'F' && int.TryParse(name[1..], out int n) && n is >= 1 and <= 12
            ? (uint)(0x70 + n - 1) : 0;
    }

    /// <summary>只在游戏是最前面的窗口时占着这个键，切到别的程序就还回去，不影响别处。</summary>
    public static void WatchHotkey(Func<string> talkKey, Func<string> bossKey, Action talk, Action boss, Action<string> say)
    {
        var thread = new Thread(() =>
        {
            var keys = new[] { talkKey, bossKey };
            var names = new[] { "说话快捷键", "老板键" };
            var held = new uint[2];
            var complained = new bool[2];
            while (true)
            {
                try
                {
                    bool front = GameWindow() != IntPtr.Zero;
                    if (front) Unhide(say);
                    for (int i = 0; i < 2; i++)
                    {
                        uint want = front ? KeyCode(keys[i]()) : 0;
                        if (want == held[i]) continue;
                        if (held[i] != 0) UnregisterHotKey(IntPtr.Zero, i + 1);
                        held[i] = 0;
                        if (want == 0) continue;
                        if (RegisterHotKey(IntPtr.Zero, i + 1, MOD_NOREPEAT, want)) { held[i] = want; complained[i] = false; }
                        else if (!complained[i])
                        {
                            complained[i] = true;
                            say($"占不到 {keys[i]()} 这个键当{names[i]}（别的程序先占了）。在游戏控制台打 {(i == 0 ? "ta key F9" : "ta boss F10")} 这样换一个。");
                        }
                    }
                    if (!front) sawAway = true;
                    while (PeekMessage(out MSG msg, IntPtr.Zero, 0, 0, PM_REMOVE))
                    {
                        if (msg.message != WM_HOTKEY) continue;
                        if ((int)msg.wParam == 2) boss(); else talk();
                    }
                }
                catch { }
                Thread.Sleep(60);
            }
        }) { IsBackground = true, Name = "SimsLinkHotkey" };
        thread.Start();
    }

    // ── 老板键 ──
    [DllImport("user32.dll")] static extern bool ShowWindowAsync(IntPtr hWnd, int command);
    const int SW_FORCEMINIMIZE = 11;      // 窗口的主人卡死了也能把它缩下去
    static bool mutedByUs;                // 是我们静的音，回到游戏时才由我们取消
    static bool sawAway;                  // 按了老板键之后，确实离开过游戏窗口

    /// <summary>把游戏窗口缩到任务栏，并把电脑静音。两样都不需要游戏配合。</summary>
    public static string Hide()
    {
        var done = new List<string>();
        try
        {
            IntPtr window = GameWindow();
            if (window != IntPtr.Zero && ShowWindowAsync(window, SW_FORCEMINIMIZE)) done.Add("游戏窗口缩下去了");
            else done.Add("游戏窗口没缩成");
        }
        catch (Exception ex) { done.Add($"缩窗口出错（{ex.Message}）"); }
        try
        {
            if (Sound.IsMuted()) done.Add("本来就是静音");
            else { Sound.Mute(true); mutedByUs = true; done.Add("静音了"); }
        }
        catch (Exception ex) { done.Add($"静音没成（{ex.Message}）"); }
        sawAway = false;
        return string.Join("，", done) + "。点任务栏上的游戏就回来，回来时自动取消静音。";
    }

    /// <summary>玩家回到游戏窗口了：是我们静的音就取消掉。</summary>
    static void Unhide(Action<string> say)
    {
        if (!mutedByUs || !sawAway) return;
        mutedByUs = false;
        try { Sound.Mute(false); say("回到游戏了，静音取消。"); }
        catch (Exception ex) { say($"取消静音没成（{ex.Message}），你自己点一下喇叭。"); }
    }

    // ── 输入法 ──
    [DllImport("imm32.dll")] static extern IntPtr ImmGetDefaultIMEWnd(IntPtr hWnd);
    [DllImport("user32.dll")] static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] static extern IntPtr GetKeyboardLayout(uint thread);
    [DllImport("user32.dll")] static extern int GetKeyboardLayoutList(int count, [Out] IntPtr[]? list);

    const uint WM_IME_CONTROL = 0x0283, WM_INPUTLANGCHANGEREQUEST = 0x0050, SMTO_ABORTIFHUNG = 0x0002;
    const int IMC_GETCONVERSIONMODE = 0x0001, IMC_SETCONVERSIONMODE = 0x0002, IMC_GETOPENSTATUS = 0x0005, IMC_SETOPENSTATUS = 0x0006;
    const int CHINESE_MODE = 1025;      // IME_CMODE_NATIVE | IME_CMODE_SYMBOL：微软拼音的「中」
    static IntPtr layoutBefore = IntPtr.Zero;   // 替玩家换过键盘的话，原来那个记在这儿，关框时换回去

    static bool IsChinese(IntPtr layout) => ((long)layout & 0x3FF) == 0x04;

    static long Ask(IntPtr imeWindow, int what, int value = 0)
    {
        SendMessageTimeout(imeWindow, WM_IME_CONTROL, (IntPtr)what, (IntPtr)value, SMTO_ABORTIFHUNG, 300, out IntPtr result);
        return (long)result;
    }

    /// <summary>把游戏窗口的输入法切到中文 / 英文。两种电脑都管：
    /// 只装了中文输入法、靠 Shift 切中英的；和中文、英文是两个键盘、靠 Win+空格 切的。</summary>
    public static string Ime(bool chinese)
    {
        try
        {
            IntPtr window = GameWindow();
            if (window == IntPtr.Zero) return "游戏不在最前面，没动输入法。";
            uint thread = GetWindowThreadProcessId(window, out _);
            IntPtr layout = GetKeyboardLayout(thread);
            if (chinese)
            {
                if (!IsChinese(layout))
                {
                    int n = GetKeyboardLayoutList(0, null);
                    var all = new IntPtr[Math.Max(n, 0)];
                    if (n > 0) GetKeyboardLayoutList(n, all);
                    IntPtr zh = all.FirstOrDefault(IsChinese);
                    if (zh == IntPtr.Zero) return "这台电脑没装中文输入法，没动。";
                    layoutBefore = layout;
                    PostMessage(window, WM_INPUTLANGCHANGEREQUEST, IntPtr.Zero, zh);
                    Thread.Sleep(150);
                }
                IntPtr ime = ImmGetDefaultIMEWnd(window);
                if (ime == IntPtr.Zero) return "找不到游戏的输入法窗口，没切成。";
                long before = Ask(ime, IMC_GETCONVERSIONMODE);
                Ask(ime, IMC_SETOPENSTATUS, 1);
                Ask(ime, IMC_SETCONVERSIONMODE, CHINESE_MODE);
                return $"模式 {before} → {Ask(ime, IMC_GETCONVERSIONMODE)}，开关 {Ask(ime, IMC_GETOPENSTATUS)}";
            }
            if (layoutBefore != IntPtr.Zero)
            {
                PostMessage(window, WM_INPUTLANGCHANGEREQUEST, IntPtr.Zero, layoutBefore);
                layoutBefore = IntPtr.Zero;
                return "换回原来的英文键盘了";
            }
            if (!IsChinese(layout)) return "本来就是英文键盘，没动。";
            IntPtr imeWindow = ImmGetDefaultIMEWnd(window);
            if (imeWindow == IntPtr.Zero) return "找不到游戏的输入法窗口，没切成。";
            long was = Ask(imeWindow, IMC_GETCONVERSIONMODE);
            long wasOpen = Ask(imeWindow, IMC_GETOPENSTATUS);
            Ask(imeWindow, IMC_SETCONVERSIONMODE, 0);
            Ask(imeWindow, IMC_SETOPENSTATUS, 0);       // 两样都设：有的输入法认模式，有的只认开关
            return $"模式 {was} → {Ask(imeWindow, IMC_GETCONVERSIONMODE)}，开关 {wasOpen} → {Ask(imeWindow, IMC_GETOPENSTATUS)}";
        }
        catch (Exception ex) { return $"切输入法的时候出错了：{ex.Message}"; }
    }

    public static string? PressC()
    {
        try
        {
            if (GameWindow() == IntPtr.Zero)
                return "游戏不在最前面（她可能切到别的窗口了），等她回到游戏里再拍。";
            var down = new INPUT { type = INPUT_KEYBOARD };
            down.U.ki = new KEYBDINPUT { wScan = SCAN_C, dwFlags = KEYEVENTF_SCANCODE };
            var up = new INPUT { type = INPUT_KEYBOARD };
            up.U.ki = new KEYBDINPUT { wScan = SCAN_C, dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP };
            int size = Marshal.SizeOf<INPUT>();
            if (SendInput(1, [down], size) != 1) return "按不动截图键（Windows 没让按）。";
            Thread.Sleep(70);
            SendInput(1, [up], size);
            return null;
        }
        catch (Exception ex) { return $"按截图键的时候出错了：{ex.Message}"; }
    }
}
