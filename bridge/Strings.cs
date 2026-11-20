// 游戏里动作、状态、家具的名字，在 mod 那头只是一个号码（字库里的钥匙），字本身在游戏的
// 字库文件里（Strings_CHS_CN.package 这种）。游戏里的 Python 读不到那些文件，这里替它读。
//
// 文件格式（DBPF 2.x 包 + STBL 字表）是照公开的格式说明写的：
//   包头 96 字节：'DBPF'，36 处是条目数，44 处是索引大小，64 处（没有就 40 处）是索引位置
//   索引：先一个标志，低三位各管「类型 / 组 / 实例高位」是不是所有条目共用一个值；
//         每条：类型、组、实例高、实例低、位置、存盘大小（最高位是标记）、解开后大小、压缩方式(2)+(2)
//   字表（类型 0x220557DA）：'STBL'，版本(2)，(1)，条数(8)，(2)，(4)，然后每条：钥匙(4)、(1)、长度(2)、UTF-8 字
//   实例号最高那个字节是语言：0x00 英文，0x02 简体中文……
using System.Buffers.Binary;
using System.Diagnostics;
using System.IO.Compression;
using System.Text;
using System.Text.Json;

static class Strings
{
    const uint STBL = 0x220557DA;

    record Table(string File, long Offset, int Size, ushort Compression, byte Locale, bool Game);

    static readonly object gate = new();
    static readonly Dictionary<uint, string> known = new();     // 查到过的
    static readonly HashSet<uint> missing = new();              // 这次开着期间查过、哪儿都没有的
    static List<Table>? tables;                                 // 所有字表在哪（只记位置，不把字全读进来）
    static byte gameLocale;
    static string cachePath = "";
    static Action<string> say = _ => { };
    static string modsDir = "";
    static Task? preparing;
    static bool saidNoGame;                     // 「没找到游戏」只说一遍，不刷屏

    public static void Init(string baseDir, Action<string> log)
    {
        say = log;
        cachePath = Path.Combine(baseDir, "SimsLinkBridge.names.json");
        try
        {
            if (!File.Exists(cachePath)) return;
            using var doc = JsonDocument.Parse(File.ReadAllText(cachePath));
            foreach (var item in doc.RootElement.EnumerateObject())
                if (uint.TryParse(item.Name, out uint key)) known[key] = item.Value.GetString() ?? "";
        }
        catch { }
    }

    /// <summary>mod 报了游戏文件夹在哪之后，在后台先把字表的位置找好，等真来问的时候就快了。</summary>
    public static void Prepare(string simsDir)
    {
        lock (gate)
        {
            string mods = Path.Combine(simsDir, "Mods");
            if (preparing != null && mods == modsDir) return;
            modsDir = mods;
            preparing = Task.Run(Scan);
        }
    }

    /// <summary>把这些钥匙对应的字找出来。等不及（字表还没找完）就先回手上有的。</summary>
    public static Dictionary<uint, string> Lookup(IEnumerable<uint> keys, int waitMs, out bool ready)
    {
        ready = false;
        var want = keys.Where(k => k != 0).Distinct().ToList();
        var found = new Dictionary<uint, string>();
        var todo = new HashSet<uint>();
        lock (gate)
        {
            foreach (uint key in want)
            {
                if (known.TryGetValue(key, out var text)) found[key] = text;
                else if (!missing.Contains(key)) todo.Add(key);
            }
            if (todo.Count == 0) { ready = true; return found; }
            preparing ??= Task.Run(Scan);
        }
        try { if (!preparing!.Wait(waitMs)) return found; } catch { return found; }
        List<Table> list;
        lock (gate) { list = tables ?? []; }
        if (list.Count == 0) return found;            // 字表一张都没找到：不记「没有」，下回再试
        var clock = Stopwatch.StartNew();
        var best = new Dictionary<uint, (int rank, string text)>();
        int read = 0;
        var trouble = new Dictionary<string, int>();      // 读不了的表：为什么 → 几张
        foreach (var table in list)
        {
            if (table.Locale != gameLocale && table.Locale != 0) continue;     // 别的语言的表用不上，不翻
            try
            {
                int rank = table.Locale == gameLocale ? 3 : 2;
                if (table.Game) rank += 3;        // 游戏自己的字库优先于别的 mod 的
                foreach (var (key, text) in ReadTable(table, todo))
                    if (!best.TryGetValue(key, out var have) || rank > have.rank) best[key] = (rank, text);
                read++;
            }
            catch (Exception ex)
            {
                string why = (table.Game ? "游戏的表 " : "mod 的表 ") + (ex is NotSupportedException ? ex.Message : ex.GetType().Name + " " + ex.Message);
                trouble[why] = trouble.GetValueOrDefault(why) + 1;
            }
        }
        lock (gate)
        {
            foreach (uint key in todo)
            {
                if (best.TryGetValue(key, out var hit)) { known[key] = hit.text; found[key] = hit.text; }
                else missing.Add(key);
            }
            if (best.Count > 0) Save();
        }
        ready = true;
        string bad = trouble.Count == 0 ? "" :
            "；有表读不了：" + string.Join("，", trouble.OrderByDescending(p => p.Value).Take(4).Select(p => $"{p.Key} ×{p.Value}"));
        say($"字库：查了 {todo.Count} 个名字，找到 {best.Count} 个（翻了 {read} 张表，{clock.ElapsedMilliseconds} 毫秒{bad}）。");
        return found;
    }

    static void Save()
    {
        try
        {
            var plain = known.ToDictionary(p => p.Key.ToString(), p => p.Value);
            File.WriteAllText(cachePath, JsonSerializer.Serialize(plain, NamesJson.Default.DictionaryStringString));
        }
        catch { }
    }

    static void Scan()
    {
        var clock = Stopwatch.StartNew();
        var list = new List<Table>();
        byte locale = 0;
        string game = GameDir();
        int gameFiles = 0, modFiles = 0;
        if (game.Length > 0)
        {
            List<string> files;
            try { files = Directory.EnumerateFiles(game, "Strings_*.package", SearchOption.AllDirectories).ToList(); }
            catch { files = []; }
            // 装了哪种语言就只有哪种的字库（外加英文）；有非英文的就用它
            var local = files.Where(f => !Path.GetFileName(f).Contains("ENG_US", StringComparison.OrdinalIgnoreCase)).ToList();
            var chosen = local.Count > 0 ? local : files;
            foreach (string file in chosen)
            {
                var found = ReadIndex(file, true);
                if (found.Count > 0) { gameFiles++; list.AddRange(found); }
            }
            var votes = list.GroupBy(t => t.Locale).OrderByDescending(g => g.Count()).FirstOrDefault();
            if (votes != null) locale = votes.Key;
        }
        string mods;
        lock (gate) { mods = modsDir; }
        if (mods.Length > 0 && Directory.Exists(mods))
        {
            IEnumerable<string> files;
            try { files = Directory.EnumerateFiles(mods, "*.package", SearchOption.AllDirectories).ToList(); }
            catch { files = []; }
            foreach (string file in files)
            {
                try
                {
                    var found = ReadIndex(file, false);
                    if (found.Count > 0) { modFiles++; list.AddRange(found); }
                }
                catch { }
            }
        }
        lock (gate) { tables = list; gameLocale = locale; missing.Clear(); }
        // 游戏自己的表是怎么压的：读不出游戏里的名字时，先看这一行
        string packing = string.Join("、", list.Where(t => t.Game).GroupBy(t => t.Compression)
            .OrderByDescending(g => g.Count()).Select(g => $"0x{g.Key:X4} {g.Count()} 张"));
        if (game.Length == 0 && saidNoGame) { lock (gate) { tables = list; preparing = null; } return; }
        saidNoGame = game.Length == 0;
        say(game.Length == 0
            ? "字库：没找到游戏装在哪（游戏开着的时候才认得出），动作名先用英文的。"
            : $"字库：游戏装在 {game}。游戏的 {gameFiles} 个、Mods 里的 {modFiles} 个文件里有名字表，共 {list.Count} 张（语言代号 {locale}，{clock.ElapsedMilliseconds} 毫秒）。游戏的表压缩方式：{(packing.Length > 0 ? packing : "一张都没有")}。");
        if (game.Length == 0) lock (gate) { preparing = null; }      // 下回再找
    }

    /// <summary>游戏装在哪：从正在跑的游戏程序倒推（…\Game\Bin\TS4_x64.exe 往上两层）。</summary>
    static string GameDir()
    {
        string forced = Environment.GetEnvironmentVariable("SIMSLINK_GAME_DIR") ?? "";
        if (forced.Length > 0) return forced;
        try
        {
            foreach (var process in Process.GetProcesses())
            {
                try
                {
                    if (!process.ProcessName.StartsWith("TS4", StringComparison.OrdinalIgnoreCase)) continue;
                    string? exe = process.MainModule?.FileName;
                    string? root = Path.GetDirectoryName(Path.GetDirectoryName(Path.GetDirectoryName(exe ?? "")));
                    if (!string.IsNullOrEmpty(root) && Directory.Exists(root)) return root;
                }
                catch { }
            }
        }
        catch { }
        return "";
    }

    static List<Table> ReadIndex(string file, bool game)
    {
        var found = new List<Table>();
        using var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        byte[] head = new byte[96];
        if (stream.Read(head, 0, 96) < 96 || head[0] != 'D' || head[1] != 'B' || head[2] != 'P' || head[3] != 'F') return found;
        if (BinaryPrimitives.ReadUInt32LittleEndian(head.AsSpan(4)) != 2) return found;
        int count = (int)BinaryPrimitives.ReadUInt32LittleEndian(head.AsSpan(36));
        int size = (int)BinaryPrimitives.ReadUInt32LittleEndian(head.AsSpan(44));
        long position = (long)BinaryPrimitives.ReadUInt64LittleEndian(head.AsSpan(64));
        if (position == 0) position = BinaryPrimitives.ReadUInt32LittleEndian(head.AsSpan(40));
        if (count <= 0 || size < 4 || size > 64 * 1024 * 1024 || position <= 0 || position + size > stream.Length) return found;
        byte[] index = new byte[size];
        stream.Position = position;
        stream.ReadExactly(index, 0, size);
        int at = 0;
        uint Next() { uint v = BinaryPrimitives.ReadUInt32LittleEndian(index.AsSpan(at)); at += 4; return v; }
        uint flags = Next();
        uint sameType = (flags & 1) != 0 ? Next() : 0;
        uint sameGroup = (flags & 2) != 0 ? Next() : 0;
        uint sameHigh = (flags & 4) != 0 ? Next() : 0;
        int each = 4 * (8 - ((flags & 1) != 0 ? 1 : 0) - ((flags & 2) != 0 ? 1 : 0) - ((flags & 4) != 0 ? 1 : 0));
        for (int i = 0; i < count && at + each <= size; i++)
        {
            uint type = (flags & 1) != 0 ? sameType : Next();
            if ((flags & 2) == 0) Next(); else _ = sameGroup;
            uint high = (flags & 4) != 0 ? sameHigh : Next();
            Next();                                   // 实例低位
            uint offset = Next();
            uint onDisk = Next() & 0x7FFFFFFF;
            Next();                                   // 解开后大小
            uint packed = Next();
            if (type != STBL || onDisk == 0 || onDisk > 64 * 1024 * 1024) continue;
            found.Add(new Table(file, offset, (int)onDisk, (ushort)(packed & 0xFFFF), (byte)(high >> 24), game));
        }
        return found;
    }

    /// <summary>EA 老式的「内部压缩」（RefPack）。照公开的格式说明写的。</summary>
    static byte[] RefPack(byte[] src)
    {
        int p = 0;
        byte kind = src[p++];
        if (src[p++] != 0xFB) throw new NotSupportedException("内部压缩的开头不对");
        int width = (kind & 0x80) != 0 ? 4 : 3;
        if ((kind & 0x01) != 0) p += width;                 // 压缩后的大小，用不上
        int size = 0;
        for (int i = 0; i < width; i++) size = (size << 8) | src[p++];
        byte[] dst = new byte[size];
        int d = 0;
        while (p < src.Length)
        {
            int b0 = src[p++], plain, copy = 0, offset = 0;
            if (b0 < 0x80) { int b1 = src[p++]; plain = b0 & 3; copy = ((b0 & 0x1C) >> 2) + 3; offset = ((b0 & 0x60) << 3) + b1 + 1; }
            else if (b0 < 0xC0) { int b1 = src[p++], b2 = src[p++]; plain = (b1 & 0xC0) >> 6; copy = (b0 & 0x3F) + 4; offset = ((b1 & 0x3F) << 8) + b2 + 1; }
            else if (b0 < 0xE0) { int b1 = src[p++], b2 = src[p++], b3 = src[p++]; plain = b0 & 3; copy = ((b0 & 0x0C) << 6) + b3 + 5; offset = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1; }
            else if (b0 < 0xFC) { plain = ((b0 & 0x1F) << 2) + 4; }
            else { plain = b0 & 3; Array.Copy(src, p, dst, d, plain); break; }
            Array.Copy(src, p, dst, d, plain);
            p += plain;
            d += plain;
            for (int i = 0; i < copy; i++, d++) dst[d] = dst[d - offset];
        }
        return dst;
    }

    static IEnumerable<(uint key, string text)> ReadTable(Table table, HashSet<uint> want)
    {
        byte[] raw = new byte[table.Size];
        using (var stream = new FileStream(table.File, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        {
            stream.Position = table.Offset;
            stream.ReadExactly(raw, 0, raw.Length);
        }
        byte[] data;
        if (table.Compression == 0x5A42)
        {
            using var packed = new ZLibStream(new MemoryStream(raw), CompressionMode.Decompress);
            using var plain = new MemoryStream();
            packed.CopyTo(plain);
            data = plain.ToArray();
        }
        else if (table.Compression == 0) data = raw;
        else if (table.Compression == 0xFFFF) data = RefPack(raw);      // 老式的「内部压缩」
        else throw new NotSupportedException($"压缩方式 0x{table.Compression:X4} 不认识");
        if (data.Length < 21 || data[0] != 'S' || data[1] != 'T' || data[2] != 'B' || data[3] != 'L')
            throw new NotSupportedException($"解开后不是字表（开头 {(data.Length >= 4 ? Convert.ToHexString(data, 0, 4) : "太短")}）");
        ulong entries = BinaryPrimitives.ReadUInt64LittleEndian(data.AsSpan(7));
        int at = 21;
        for (ulong i = 0; i < entries && at + 7 <= data.Length; i++)
        {
            uint key = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(at));
            int length = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(at + 5));
            at += 7;
            if (at + length > data.Length) yield break;
            if (want.Contains(key)) yield return (key, Encoding.UTF8.GetString(data, at, length));
            at += length;
        }
    }
}

[System.Text.Json.Serialization.JsonSerializable(typeof(Dictionary<string, string>))]
partial class NamesJson : System.Text.Json.Serialization.JsonSerializerContext { }
