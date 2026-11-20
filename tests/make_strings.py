"""造两个假的字库文件，给小转发程序读（python3）。格式照公开的 DBPF 2.x / STBL 说明写：
跟 bridge/Strings.cs 是同一份理解，所以这个测试只能证明「读和写对得上」，
真游戏的文件读不读得出来，要在真电脑上看黑窗口里那行「字库：……」。

  <game>/Data/Client/Strings_CHS_CN.package   简体中文，zlib 压缩，索引不共用字段
  <game>/Data/Client/Strings_ENG_US.package   英文（有中文的时候不该被用到）
  <mods>/WW/ww.package                        别的 mod 的字表：英文、不压缩、索引共用类型/组/实例高位
"""
import os
import struct
import sys
import zlib

STBL = 0x220557DA


def key(name):
    return zlib.crc32(name.encode('utf-8')) & 0xFFFFFFFF


def stbl(pairs):
    body = b''.join(struct.pack('<IBH', k, 0, len(t.encode('utf-8'))) + t.encode('utf-8') for k, t in pairs)
    return b'STBL' + struct.pack('<HBQHI', 5, 0, len(pairs), 0, sum(len(t.encode('utf-8')) + 1 for _k, t in pairs)) + body


def refpack(raw):
    """最笨的 RefPack：全是「原样照抄」的段，中间故意插一次「回头抄 3 个字节」，够验解压那头了。"""
    out = bytearray([0x10, 0xFB]) + len(raw).to_bytes(3, 'big')
    at = 0

    def literal(n):
        nonlocal at
        while n >= 4:
            take = min(112, n - n % 4)
            out.append(0xE0 + (take - 4) // 4)
            out.extend(raw[at:at + take])
            at += take
            n -= take
        return n

    cut = None
    for i in range(8, len(raw) - 3):                 # 找一处「这 3 个字节前面 1023 以内出现过」
        j = raw.rfind(raw[i:i + 3], max(0, i - 1000), i + 2)
        if 0 <= j < i and (i % 4) == 0:
            cut = (i, i - j)
            break
    if cut:
        literal(cut[0])
        offset = cut[1] - 1
        out.append(((offset >> 8) << 5) | (0 << 2) | 0)   # 抄 3 个，前面不带原样字节
        out.append(offset & 0xFF)
        at += 3
    rest = literal(len(raw) - at)
    out.append(0xFC + rest)
    out.extend(raw[at:at + rest])
    return bytes(out)


def package(path, tables, shared=False):
    """tables: [(实例高位, 实例低位, 字表字节, 压不压)]；压不压：True=zlib，'refpack'=老式内部压缩"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    blobs, entries, offset = [], [], 96
    for high, low, raw, packed in tables:
        data = refpack(raw) if packed == 'refpack' else zlib.compress(raw) if packed else raw
        entries.append((high, low, offset, len(data), len(raw), 0xFFFF if packed == 'refpack' else 0x5A42 if packed else 0))
        blobs.append(data)
        offset += len(data)
    if shared:
        index = struct.pack('<IIII', 7, STBL, 0, tables[0][0])
        for _high, low, off, size, mem, comp in entries:
            index += struct.pack('<IIIIHH', low, off, size | 0x80000000, mem, comp, 1)
    else:
        index = struct.pack('<I', 0)
        for high, low, off, size, mem, comp in entries:
            index += struct.pack('<IIIIIIIHH', STBL, 0, high, low, off, size | 0x80000000, mem, comp, 1)
    head = bytearray(96)
    head[0:4] = b'DBPF'
    struct.pack_into('<II', head, 4, 2, 1)
    struct.pack_into('<I', head, 36, len(entries))
    struct.pack_into('<I', head, 44, len(index))
    struct.pack_into('<I', head, 60, 3)
    struct.pack_into('<Q', head, 64, offset)
    with open(path, 'wb') as f:
        f.write(bytes(head) + b''.join(blobs) + index)


CHS = [
    ('mixer_social_Kiss_targeted_romance', '亲吻'),
    ('mixer_social_Hug_targeted_friendly', '拥抱{1.SimFirstName}'),
    ('sim_Chat', '聊天'),
    ('sim-stand', '聊天'),                      # 故意重名：列出来要带上内部名才分得清
    ('fridge_Cook', '做饭'),
    ('bed_Sleep', '睡觉'),
    ('bed_Nap', '{M0.他}{F0.她}小睡一下'),
    ('Buff_FirstKiss', '初吻'),
]

if __name__ == '__main__':
    game, mods = sys.argv[1], sys.argv[2]
    half = len(CHS) // 2
    package(os.path.join(game, 'Data', 'Client', 'Strings_CHS_CN.package'), [
        (0x02000000, 1, stbl([(key(n), t) for n, t in CHS[:half]]), True),
        (0x02000000, 2, stbl([(key(n), t) for n, t in CHS[half:]]), 'refpack'),
        (0x02000000, 3, b'not a table at all', False),          # 坏表：要在黑窗口里报出来，不能悄悄吞掉
    ])
    package(os.path.join(game, 'Data', 'Client', 'Strings_ENG_US.package'), [
        (0x00000000, 1, stbl([(key(n), 'EN ' + n) for n, _t in CHS]), True),
    ])
    package(os.path.join(mods, 'WW', 'ww.package'), [
        (0x00000000, 9, stbl([(key('phone_JoinCareer'), 'Join a Career'), (key('sim_Chat'), 'mod 不该盖过游戏的')]), False),
    ], shared=True)
    print('ok')
