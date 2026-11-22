"""Sims 4 里的 mod（SulSul）把游戏写成字交上来，AI 的话和动作从这里带回游戏。

这个文件是纯逻辑：收什么、存哪、怎么写成给 AI 看的字。不碰网络，不等任何东西；
等指令 / 等结果 / 推送那部分在 app.py。单测 tests/test_core.py。

读代码的人注意两个代词：注释和文案里的「她」是玩游戏的那个人，「他 / 你」是 AI。
给 AI 看的字里，「她」可以在出口处换成别的称呼（SETTINGS.pronoun，见 voice()）。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

LIVE_SECONDS = 20            # mod 每两秒敲一次门；这么久没来 = 游戏关了 / 转发程序没开
MAX_BODY = 200_000
MAX_EVENTS_PER_SYNC = 60
EVENTS_KEEP = 400
RECENT_SHOWN = 12
COMMAND_TTL = 25             # 他的指令这么久没被游戏取走就作废
TOLD_TTL = 600               # 她连着说话时，这么久之内只递变了的；过了就重新给一整张
OPS = ("say", "list", "do", "objects", "cancel", "speed", "photo", "outfit", "money", "moodlets")
MONEY_MAX = 50000            # AI 一次最多给她打这么多
PHOTO_WAIT = 30              # 拍照要等：按快门 → 游戏存图 → 她电脑传上来
PHOTO_MAX_BYTES = 14 * 1024 * 1024
PHOTO_EDGE = 1600            # 传上来的截图缩到长边这么多、转成 JPG：省地方，也省他看图的上下文
HER_BATCH_MAX = 6            # 她一口气发来的截图，一条消息最多带这么多张
MIRROR_MAX = 360             # AI 在聊天里回的话弹进游戏时，一条通知最多这么多字
MIRROR_PIECES = 3            # 一条回话太长就按段拆，最多拆这么多条
MIRROR_SAME = 120            # 这么多秒内他已经在游戏里说过同一句，就不再弹第二遍


class Settings:
    """这台服务器怎么接的 AI。app.py 启动时按配置填。"""
    pronoun = "她"      # 给 AI 看的字里怎么称呼玩家：她 / 他 / TA
    mirror = False      # AI 的回话会不会自动弹进游戏（接了 /sims/reply 才会）


SETTINGS = Settings()
_KEEP = "\ue000"      # 玩家自己打的字里的「她」先换成这个，出口处再换回来，免得被改掉

SPOKEN_MIRROR = "你照常回话就行：她开着游戏的时候，你回的每一句都会自动弹在她游戏右上角，不用再调 say。一句别太长。"
SPOKEN_TOOL = "想让她在游戏里看到你的话：用 sims 工具 action=say，会弹在她游戏右上角。一句别太长。"
MARK_HINT = "想让你的小人做事，直接在回话里写记号，不用调工具：⟪小人:亲吻 → 小椴⟫、⟪小人:睡觉 → Bed⟫、⟪小人:穿 睡衣⟫、⟪小人:取消⟫。记号她看不到。"
DO_HINT = "想让你的小人做事：sims 工具 action=list 看能做什么，action=do 去做。"


def spoken() -> str:
    return SPOKEN_MIRROR if SETTINGS.mirror else SPOKEN_TOOL


def act_hint() -> str:
    return MARK_HINT if SETTINGS.mirror else DO_HINT


def quote(text) -> str:
    """玩家 / AI 自己说的话要原样留着：里面的「她」不跟着换称呼。"""
    text = str(text or "")
    return text.replace("她", _KEEP) if SETTINGS.pronoun != "她" else text


def voice(text: str) -> str:
    """出口：给 AI 看的每一段字都过这里，把「她」换成配置里的称呼。"""
    text = str(text or "")
    if SETTINGS.pronoun == "她":
        return text
    return text.replace("她", SETTINGS.pronoun).replace(_KEEP, "她")

MARKS_MAX = 6                # 一条回话里最多认这么多个小人记号
_MARK_RE = re.compile(r"\*{0,2}[ \t]*[⟪《【\[]\s*小人\s*[:：]\s*([^⟫》】\]\n]{1,120})[⟫》】\]][ \t]*\*{0,2}")
_ARROW_RE = re.compile(r"\s*(?:→|->|=>|－>|—>)\s*")

# 游戏叫醒他：她没说话，但游戏里出了他会想知道的事
WAKE_GAP = 300               # 两次叫醒之间至少隔这么久
WAKE_GAP_BIG = 45            # 大事（怀孕、生了、有人去世、着火、家里多了人、结婚）不等那么久
WAKE_SAME = 600              # 同一个人的同一种事，这么久之内只叫一次
WAKE_IDLE = 45 * 60          # 她连着玩了这么久一句话没跟他说
WAKE_DAILY_MAX = 40          # 一天最多叫这么多次：每叫一次是他完整的一轮
WAKE_LOW = -75               # 她的需求掉到这以下算见底
WAKE_LOW_REARM = -50         # 回到这以上才算爬出来，下次再掉才再叫
SESSION_GAP = 120            # 这么久没敲门 = 游戏关过，「连着玩了多久」从头算
ROMANCE_WORDS = ("romance", "kiss", "woohoo", "flirt", "makeout", "make_out", "wickedwhims_sex",
                 "propos", "embrace", "caress", "seduc")
BOND_WORDS = ("married", "engaged", "divorc", "brokenup", "broken_up", "broke_up")

MOTIVES = {"Hunger": "饿", "Energy": "精力", "Bladder": "膀胱", "Fun": "娱乐", "Social": "社交", "Hygiene": "卫生"}
MOODS = {
    "Happy": "开心", "Fine": "平静", "Sad": "难过", "Angry": "生气", "Flirty": "调情", "Focused": "专注",
    "Energized": "精力充沛", "Confident": "自信", "Inspired": "有灵感", "Playful": "顽皮", "Embarrassed": "尴尬",
    "Uncomfortable": "不舒服", "Tense": "紧张", "Bored": "无聊", "Dazed": "恍惚", "Scared": "害怕",
    "Asleep": "睡着", "Possessed": "被附身", "Stressed": "压力大",
}
DAYS = "日一二三四五六"
# 她在哪个界面（mod 每趟都报）。live=游戏里；别的时候小人动不了。
SCREENS = ("live", "build", "cas", "loading", "away")
SCREEN_HEAD = {
    "build": "她在建造模式摆家具盖房子，游戏里的时间停着",
    "cas": "她在捏人界面，游戏世界停着，下面是她进去之前的样子",
    "loading": "游戏在读盘，下面是读盘之前的样子",
    "away": "她不在存档里（主菜单或地图），下面是她离开之前的样子",
}
SCREEN_EVENT = {
    "live": "她回到游戏里了",
    "build": "她进了建造模式",
    "cas": "她进了捏人界面",
    "loading": "游戏在读盘",
    "away": "她退出了存档（主菜单或地图）",
}
SCREEN_BLOCKS = {
    "cas": "她在捏人界面，游戏世界停着，小人动不了。等她捏完回来再做；想说话可以 say。",
    "loading": "游戏在读盘，等一会儿再试。",
    "away": "她不在存档里（主菜单或地图），小人动不了。",
}


# ───────────────────────── 收 ─────────────────────────

def clean_sync(body: dict) -> dict:
    """校验 mod 交上来的一包；不对就 ValueError。"""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    try:
        after = max(0, int(body.get("after") or 0))
    except (TypeError, ValueError):
        after = 0
    try:
        wait = min(5.0, max(0.0, float(body.get("wait") or 0)))
    except (TypeError, ValueError):
        wait = 0.0
    state = body.get("state")
    if state is not None and not isinstance(state, dict):
        raise ValueError("state must be an object")
    events = [e for e in (body.get("events") or []) if isinstance(e, dict)][-MAX_EVENTS_PER_SYNC:]
    results = [r for r in (body.get("results") or []) if isinstance(r, dict) and "id" in r][-MAX_EVENTS_PER_SYNC:]
    for event in events:
        if event.get("t") == "say":
            event["text"] = str(event.get("text") or "").strip()[:1000]
    screen = body.get("screen")
    screen = screen if screen in SCREENS else None
    return {"after": after, "wait": wait, "state": state, "events": events, "results": results, "screen": screen}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def record(root: Path, sync: dict, now: float | None = None) -> None:
    """存这一包：状态覆盖、事件追加、「刚来过」的时间。"""
    now = time.time() if now is None else now
    root.mkdir(parents=True, exist_ok=True)
    if sync.get("state") is not None:
        _write(root / "state.json", {"at": now, "state": sync["state"]})
    seen = {"at": now}
    screen = sync.get("screen") or (_read(root / "seen.json") or {}).get("screen")
    if screen:
        seen["screen"] = screen
    _write(root / "seen.json", seen)
    events = sync.get("events") or []
    if events:
        log = root / "events.jsonl"
        with log.open("a", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(dict(event, at=now), ensure_ascii=False) + "\n")
        lines = log.read_text(encoding="utf-8").splitlines()
        if len(lines) > EVENTS_KEEP * 2:
            log.write_text("\n".join(lines[-EVENTS_KEEP:]) + "\n", encoding="utf-8")


def last_seen(root: Path) -> float:
    return float((_read(root / "seen.json") or {}).get("at") or 0)


def screen(root: Path) -> str:
    """她在哪个界面；旧版 mod 不报，就当在游戏里。"""
    return str((_read(root / "seen.json") or {}).get("screen") or "live")


def blocked_reason(root: Path, op: str) -> str:
    """她不在游戏世界里的时候，除了说话别的都做不了：直接告诉他为什么，不让他干等。"""
    return "" if op == "say" else SCREEN_BLOCKS.get(screen(root), "")


def is_live(root: Path, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return now - last_seen(root) <= LIVE_SECONDS


def recent_events(root: Path, limit: int = RECENT_SHOWN) -> list[dict]:
    try:
        lines = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines[-limit * 3:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:]


# ───────────────────────── AI 的指令 ─────────────────────────

def clean_command(body: dict) -> dict:
    """他要做的事：op + args。不认识的 op 直接 ValueError。"""
    op = str((body or {}).get("op") or "").strip()
    if op not in OPS:
        raise ValueError(f"op 只能是 {' / '.join(OPS)}")
    raw = (body or {}).get("args") or {}
    if not isinstance(raw, dict):
        raise ValueError("args must be an object")
    args = {}
    for key in ("who", "target", "name", "filter", "text", "speed"):
        if raw.get(key) not in (None, ""):
            args[key] = str(raw[key]).strip()[:1500]
    if raw.get("reply"):
        args["reply"] = True
    if op == "money":
        try:
            amount = int(float(raw.get("amount")))
        except (TypeError, ValueError):
            amount = 0
        if amount < 1 or amount > MONEY_MAX:
            raise ValueError(f"money 要带 amount：1 到 {MONEY_MAX} 之间的整数")
        args["amount"] = amount
    if op == "say" and not args.get("text"):
        raise ValueError("say 要带 text")
    if op == "do" and not args.get("name"):
        raise ValueError("do 要带 name（list 里的动作名）")
    if op == "speed" and args.get("speed") not in ("pause", "0", "1", "2", "3"):
        raise ValueError("speed 只能是 pause / 1 / 2 / 3")
    return {"op": op, "args": args}


def next_command_id(last_id: int, now: float | None = None) -> int:
    """指令号用毫秒时间：服务器重启也只会往上走，mod 记着的「收到第几条」不会乱。"""
    now = time.time() if now is None else now
    return max(int(now * 1000), last_id + 1)


def pending_commands(commands: list[dict], after: int, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    return [{"id": c["id"], "op": c["op"], "args": c["args"]}
            for c in commands if c["id"] > after and now - c["at"] <= COMMAND_TTL]


def prune_commands(commands: list[dict], now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    return [c for c in commands if now - c["at"] <= COMMAND_TTL]


# ───────────────────────── 写成给他看的字 ─────────────────────────

def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} 秒前"
    if seconds < 5400:
        return f"{seconds // 60} 分钟前"
    return f"{seconds // 3600} 小时前"


def _act(item: dict) -> str:
    # cn 是她屏幕上显示的名字（mod 查得到才有）；name 是内部名，认动作靠它
    return str(item.get("cn") or item["name"]) + (f" → {item['target']}" if item.get("target") else "")


def _span(minutes: int) -> str:
    minutes = int(minutes)
    if minutes >= 1440:
        return f"{minutes // 1440} 天 {(minutes % 1440) // 60} 小时"
    if minutes >= 60:
        return f"{minutes // 60} 小时 {minutes % 60} 分"
    return f"{minutes} 分钟"


def _buff_text(buff, timeless: bool = False) -> str:
    """一个情绪状态：名字（哪种情绪加几｜从哪来｜还剩多久）。旧版 mod 只报名字。"""
    if not isinstance(buff, dict):
        return str(buff)
    bits = []
    if buff.get("mood"):
        mood = MOODS.get(buff["mood"], buff["mood"])
        bits.append(f"{mood} +{buff['w']}" if buff.get("w") else mood)
    source = str(buff.get("from") or "").strip("（）() ")
    if source.startswith("来自"):                # 游戏里这句本身就写着「（来自……）」
        source = source[2:].strip("：: ")
    if source:
        bits.append(f"来自 {source}")
    if buff.get("left") and not timeless:
        bits.append(f"还剩 {_span(buff['left'])}")
    title = str(buff.get("t") or "?")
    return f"{title}（{'｜'.join(bits)}）" if bits else title


def _buffs_line(sim: dict, timeless: bool = False) -> str:
    # 带上名字：这一行会单独出现在「只列变了的」里，得看得出是谁的
    return f"  {sim.get('name', '?')} 的状态：" + "、".join(_buff_text(b, timeless) for b in (sim.get("buffs") or [])[:8])


def _sim_line(sim: dict, timeless: bool = False, with_buffs: bool = True) -> str:
    tags = []
    if sim.get("his"):
        tags.append("你")
    if sim.get("hers"):
        tags.append("她")
    if sim.get("active"):
        tags.append("她正点着的")
    head = sim.get("name", "?") + (f"（{'，'.join(tags)}）" if tags else "")
    if not sim.get("here"):
        return f"{head}：不在这块地上"
    parts = []
    if sim.get("outfit"):
        parts.append(f"穿 {sim['outfit']}")
    mood = sim.get("mood") or {}
    if mood.get("name"):
        level = f" {mood['level']}" if mood.get("level") else ""
        parts.append(f"心情 {MOODS.get(mood['name'], mood['name'])}{level}")
    doing = sim.get("doing") or []
    parts.append("在 " + "；".join(_act(d) for d in doing[-3:]) if doing else "闲着")
    queue = sim.get("queue") or []
    if queue:
        parts.append("排队 " + "；".join(_act(q) for q in queue[:4]))
    low = [f"{MOTIVES.get(k, k)} {v}" for k, v in (sim.get("motives") or {}).items()
           if v <= -30 and ":" not in k]      # 带冒号的是别的 mod 加的数值，刻度不一样，不当需求报
    if low:
        parts.append("告急 " + "、".join(low))
    if sim.get("pregnant"):
        parts.append("怀孕中")
    if sim.get("near"):
        parts.append("身边 " + "、".join(sim["near"]))
    line = f"{head}：" + "｜".join(parts)
    if sim.get("buffs") and with_buffs:
        line += "\n" + _buffs_line(sim, timeless)
    return line


def _pair_lines(sims: list[dict]) -> list[str]:
    """他和家里每个人的关系；没有「他」就不写。"""
    his = next((s for s in sims if s.get("his")), None)
    if not his:
        return []
    out = []
    for other, rel in (his.get("rel") or {}).items():
        bits = []
        if "friend" in rel:
            bits.append(f"友情 {rel['friend']}")
        if "romance" in rel:
            bits.append(f"恋爱 {rel['romance']}")
        if rel.get("bits"):
            bits.append("、".join(rel["bits"][:6]))
        if bits:
            out.append(f"你和{other}：" + "｜".join(bits))
    return out


def format_event(event: dict) -> str:
    kind = event.get("t")
    if kind == "say":
        return f"她在游戏里说：「{quote(event.get('text', ''))}」"
    if kind == "photo":
        if event.get("by") == "him":
            return "你拍了一张照片"
        return f"她发来 {int(event.get('count') or 1)} 张游戏截图"
    if kind == "he":
        return f"你在游戏里说：「{quote(event.get('text', ''))}」"
    if kind == "act":
        return f"{event.get('who', '?')} 开始 {_act(event)}"
    if kind == "mood":
        return f"{event.get('who', '?')} 心情变成 {MOODS.get(event.get('mood'), event.get('mood'))}"
    if kind == "pregnant":
        return f"{event.get('who', '?')} " + ("怀孕了" if event.get("on") else "不再是怀孕状态（生了或没了）")
    if kind == "here":
        return f"{event.get('who', '?')} " + ("到这块地上了" if event.get("on") else "离开这块地了")
    if kind == "zone":
        return "换地方了：" + ((event.get("zone") or {}).get("lot") or "新地方")
    if kind == "screen":
        return SCREEN_EVENT.get(event.get("screen"), "")
    if kind == "left":
        return "她退出了存档（回主菜单或在读盘）"
    if kind == "did":      # 他用 ⟪小人:…⟫ 记号排的事，游戏回的话
        return f"你用记号排的「{event.get('label', '?')}」：{event.get('text') or ('排上了' if event.get('ok') else '没排上')}"
    if kind == "fire":
        return "着火了" if event.get("on") else "火灭了"
    if kind == "death":
        return f"{event.get('who', '?')} 去世了"
    return ""


def format_now(root: Path, now: float | None = None) -> str:
    """给他的一整段：现在什么样 + 最近发生了什么。"""
    now = time.time() if now is None else now
    saved = _read(root / "state.json")
    seen = last_seen(root)
    if not saved:
        if seen and now - seen <= LIVE_SECONDS:      # mod 在敲门了，但还没交过一张状态：她在主菜单或读盘
            return "〔Sims 4 · 连着｜她还没进到存档里（主菜单或读盘）〕"
        return "〔Sims 4〕游戏还没连上过：她得先打开小转发程序（SulSulBridge），再进游戏。"
    state = saved.get("state") or {}
    live = now - seen <= LIVE_SECONDS
    if not live:
        head = f"〔Sims 4 · 没连着（上次 {_ago(now - seen)}），下面是她关游戏前的样子〕"
    elif screen(root) in SCREEN_HEAD:
        head = f"〔Sims 4 · 连着｜{SCREEN_HEAD[screen(root)]}〕"
    else:
        head = "〔Sims 4 · 连着，她正在玩〕"
    lines = [head] + [text for _key, text, _same in _body_rows(state)]
    recent = [(e, format_event(e)) for e in recent_events(root)]
    recent = [(e, text) for e, text in recent if text]
    if recent:
        lines.append("最近：")
        lines.extend(f"- {_ago(now - float(e.get('at') or now))} {text}" for e, text in recent)
    return "\n".join(lines)


def _clock_text(state: dict) -> str:
    clock = state.get("clock") or {}
    when = ""
    if "hour" in clock:
        when = f"周{DAYS[int(clock.get('day', 0)) % 7]} {int(clock['hour']):02d}:{int(clock.get('minute', 0)):02d}"
    speed = f"速度 {clock['speed']}" if clock.get("speed") else ""
    return "｜".join(part for part in (when, speed) if part)


def _body_rows(state: dict) -> list[tuple[str, str, str]]:
    """状态的每一行：(钥匙, 给他看的字, 用来比较变没变的字)。时间每秒都在走，不算「变了」。"""
    zone = state.get("zone") or {}
    where = zone.get("lot") or "某块地"
    if zone.get("home"):
        where += "（自己家）"
    elif zone.get("venue"):
        where += f"（{zone['venue']}）"
    clock = _clock_text(state)
    funds = f"｜家里存款 §{int(state['funds']):,}" if isinstance(state.get("funds"), (int, float)) else ""
    rows = [("where", f"地点：{where}" + (f"｜{clock}" if clock else "") + funds, where)]
    if state.get("fire"):
        rows.append(("fire", "⚠ 这块地上着火了", "fire"))
    sims = state.get("sims") or []
    for sim in sims:
        # 「还剩多久」每分钟都在变：给他看的带着，比较「变没变」的不带
        # 情绪状态单独算一行：小人换了件事做，不用把一长串状态再念一遍；状态变了也不用重念他在干嘛
        name = sim.get("name", "?")
        rows.append((f"sim:{name}", _sim_line(sim, with_buffs=False), _sim_line(sim, with_buffs=False)))
        if sim.get("buffs") and sim.get("here"):
            rows.append((f"buffs:{name}", _buffs_line(sim), _buffs_line(sim, timeless=True)))
    for index, line in enumerate(_pair_lines(sims)):
        rows.append((f"pair:{index}", line, line))
    rows.extend(_other_rows(state))
    return rows


def _other_rows(state: dict) -> list[tuple[str, str, str]]:
    """家里人以外的小人。游戏会把整条街的路人都载进来，不分开写的话，
    AI 会把街上的路人读成「窗外有八个人在看」。mod 报 others（真在这块地上的）和 street（路人）。"""
    others = [str(name) for name in (state.get("others") or []) if name]
    street = state.get("street")
    if not isinstance(street, dict):   # mod 没报 street：分不清谁在屋里谁在街上，照实说
        if not others:
            return []
        line = "这一带的别人（街上路过的也算在里面，不一定在你们身边）：" + "、".join(others)
        return [("others", line, line)]
    line = ("这块地上的别人：" + "、".join(others)) if others else "这块地上没有别的小人"
    rows = [("others", line, line)]
    try:
        count = int(street.get("n") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        names = [str(name) for name in (street.get("names") or []) if name][:6]
        line = f"街上路过的（不在这块地上，只是游戏载入的路人）：{count} 人"
        if names:
            line += "，有 " + "、".join(names) + ("等" if count > len(names) else "")
        rows.append(("street", line, "street"))   # 路人来来去去不算「变了」
    return rows


def note_for_him(root: Path, now: float | None = None) -> str:
    """她在游戏里每说一句都要带上游戏的样子。十分钟内接着说的话，只递变了的那几行
    和新发生的事——整张反复递，一晚上能吃掉他几万字的上下文。
    头一句、隔了十分钟、或者她换了界面，才给完整的一张。"""
    now = time.time() if now is None else now
    full, body = _note_parts(root, now)
    if full:
        return tell_him_note(body)
    return ("（在游戏里说的；你照常回，话会自动弹在她游戏里）\n" if SETTINGS.mirror
            else "（在游戏里说的；回她用 sims 工具 action=say）\n") + body


def _note_body(root: Path, now: float) -> str:
    """游戏的样子，不带「这句是她说的」那层话：游戏叫醒他的时候用。"""
    return _note_parts(root, now)[1]


def _note_parts(root: Path, now: float) -> tuple[bool, str]:
    """(是不是完整的一张, 字)。跟他上一次看到的比：十分钟内只给变了的。"""
    saved = _read(root / "state.json")
    if not saved:
        return True, format_now(root, now)
    state = saved.get("state") or {}
    rows = _body_rows(state)
    head_key = f"{is_live(root, now)}|{screen(root)}"
    told = _read(root / "told.json") or {}
    _write(root / "told.json", {"at": now, "head": head_key, "rows": {key: same for key, _text, same in rows}})
    before = told.get("rows")
    if not isinstance(before, dict) or told.get("head") != head_key or now - float(told.get("at") or 0) > TOLD_TTL:
        return True, format_now(root, now)
    changed = [text for key, text, same in rows if before.get(key) != same]
    told_at = float(told.get("at") or 0)
    fresh = [(e, format_event(e)) for e in recent_events(root)
             if float(e.get("at") or 0) > told_at and e.get("t") not in ("say", "he")]
    fresh = [(e, text) for e, text in fresh if text][-8:]
    clock = _clock_text(state)
    tail = f"｜{clock}" if clock else ""
    if not changed and not fresh:
        return False, f"〔Sims 4 · 跟上一句时一样{tail}〕"
    lines = [f"〔Sims 4 · 接着上一句，只列变了的{tail}〕"] + changed
    if fresh:
        lines.append("刚才：")
        lines.extend(f"- {_ago(now - float(e.get('at') or now))} {text}" for e, text in fresh)
    return False, "\n".join(lines)


# ───────────────────────── 游戏叫醒他 ─────────────────────────

def _wake_state(root: Path) -> dict:
    data = _read(root / "wake.json") or {}
    data.setdefault("on", True)
    data.setdefault("keys", {})
    data.setdefault("low", [])
    return data


def wake_on(root: Path) -> bool:
    return bool(_wake_state(root).get("on", True))


def set_wake(root: Path, on: bool) -> None:
    data = _wake_state(root)
    data["on"] = bool(on)
    _write(root / "wake.json", data)


def _is_romance(name: str) -> bool:
    low = str(name or "").lower()
    return any(word in low for word in ROMANCE_WORDS)


def _last_talk(root: Path) -> float:
    """他们俩上一次在游戏里说上话（她说、他说、发照片）是什么时候。"""
    latest = 0.0
    for event in recent_events(root, limit=EVENTS_KEEP):
        if event.get("t") in ("say", "he", "photo"):
            latest = max(latest, float(event.get("at") or 0))
    return latest


def _wake_candidates(old: dict, state: dict, events: list[dict], low_now: list[str]) -> list[dict]:
    """这一包里有哪些事值得叫他。每条：key（同类事的冷却用）、big（大事）、text。"""
    sims = state.get("sims") or []
    his = next((s for s in sims if s.get("his")), None)
    hers = next((s for s in sims if s.get("hers")), None)
    his_name = (his or {}).get("name")
    her_name = (hers or {}).get("name")
    family = {s.get("name") for s in sims}
    people = family | set(state.get("others") or []) | set((state.get("street") or {}).get("names") or [])
    out = []
    for event in events:
        kind, who = event.get("t"), event.get("who")
        if kind == "pregnant":
            out.append({"key": f"pregnant:{who}:{bool(event.get('on'))}", "big": True, "text": format_event(event)})
        elif kind == "death":
            out.append({"key": f"death:{who}", "big": True, "text": format_event(event)})
        elif kind == "fire" and event.get("on"):
            out.append({"key": "fire", "big": True, "text": "这块地上着火了"})
        elif kind == "act" and _is_romance(event.get("name")):
            target = event.get("target") or ""
            if who and who == her_name:
                if target in people and target != his_name:
                    out.append({"key": f"jealous:{target}", "text": f"{who} 开始 {_act(event)}（{target} 不是你）"})
                elif target not in people:
                    # 目标是家具（WW 的动作多半这样）：看他自己是不是也在做；不是的话看她身边是谁
                    mine = (his or {}).get("doing") or []
                    queued = (his or {}).get("queue") or []
                    if any(_is_romance(item.get("name")) for item in mine + queued):
                        continue
                    near = [n for n in (hers or {}).get("near") or [] if n != his_name]
                    if near:
                        out.append({"key": f"jealous:{near[0]}",
                                    "text": f"{who} 开始 {_act(event)}（身边是 {'、'.join(near[:3])}，不是你）"})
            elif who and who == his_name and target in people and target != her_name:
                out.append({"key": f"stray:{target}",
                            "text": f"你的小人自己去 {_act(event)} 了（不是你点的，是小人自己逛着逛着去的）"})
    before = {s.get("name"): s for s in (old.get("sims") or [])}
    if before and family & set(before):          # 同一个存档才比；换了存档不算
        for sim in sims:
            if sim.get("name") not in before:
                out.append({"key": f"join:{sim.get('name')}", "big": True, "text": f"家里多了一个人：{sim.get('name')}"})
        old_his = before.get(his_name) or {}
        for other, rel in ((his or {}).get("rel") or {}).items():
            had = set(((old_his.get("rel") or {}).get(other) or {}).get("bits") or [])
            if other not in (old_his.get("rel") or {}):
                continue
            for bit in rel.get("bits") or []:
                if bit not in had and any(word in bit.lower() for word in BOND_WORDS):
                    out.append({"key": f"bond:{other}:{bit}", "big": True, "text": f"你和{other}的关系多了一条：{bit}"})
    for motive, value in ((hers or {}).get("motives") or {}).items():
        if motive not in MOTIVES:             # 别的 mod 加的数值（WW 的满足度之类）不算需求见底
            continue
        if isinstance(value, (int, float)) and value <= WAKE_LOW and motive not in low_now:
            out.append({"key": f"low:{motive}", "low": motive,
                        "text": f"{her_name} 的{MOTIVES.get(motive, motive)}掉到 {int(value)} 了"})
    return out


def wake_plan(root: Path, sync: dict, now: float | None = None) -> dict | None:
    """这一包要不要叫醒他。要在 record() 之前问：得拿旧的那张状态来比。
    决定叫，就当场记账（冷却、今天第几次）；回的东西交给 wake_text() 拼字。"""
    now = time.time() if now is None else now
    data = _wake_state(root)
    dirty = False
    if now - last_seen(root) > SESSION_GAP:      # 游戏关过：这是新的一场
        data["since"] = now
        dirty = True
    for event in sync.get("events") or []:       # 她在游戏里打 mu wake on / off
        if event.get("t") == "wake":
            data["on"], dirty = bool(event.get("on")), True
    saved = _read(root / "state.json") or {}
    old = saved.get("state") or {}
    state = sync.get("state") or old
    hers = next((s for s in state.get("sims") or [] if s.get("hers")), None)
    motives = (hers or {}).get("motives") or {}
    low = [m for m in data["low"] if isinstance(motives.get(m), (int, float)) and motives[m] <= WAKE_LOW_REARM]
    if low != data["low"]:
        data["low"], dirty = low, True

    def done(plan):
        if dirty or plan:
            _write(root / "wake.json", data)
        return plan

    screen_now = sync.get("screen") or screen(root)
    if not data["on"] or screen_now != "live" or her_says(sync):
        return done(None)
    found = _wake_candidates(old if sync.get("state") else {}, state, sync.get("events") or [], low)
    found = [c for c in found if now - float(data["keys"].get(c["key"]) or 0) >= WAKE_SAME]
    last = float(data.get("last") or 0)
    if not found:
        since = max(float(data.get("since") or now), last)
        if now - since >= WAKE_IDLE and now - max(since, _last_talk(root)) >= WAKE_IDLE:
            minutes = int((now - max(float(data.get("since") or now), _last_talk(root))) // 60)
            found = [{"key": "idle", "text": f"她已经连着玩了 {minutes} 分钟，一句话没跟你说"}]
    if not found:
        return done(None)
    big = any(c.get("big") for c in found)
    if now - last < (WAKE_GAP_BIG if big else WAKE_GAP):
        return done(None)
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if data.get("day") != day:
        data["day"], data["count"] = day, 0
    if int(data.get("count") or 0) >= WAKE_DAILY_MAX:
        return done(None)
    data["count"] = int(data.get("count") or 0) + 1
    data["last"] = now
    for c in found:
        data["keys"][c["key"]] = now
        if c.get("low"):
            data["low"].append(c["low"])
    data["keys"] = {k: at for k, at in data["keys"].items() if now - float(at) < 86400}
    dirty = True
    return done({"reasons": [c["text"] for c in found][:6], "count": data["count"]})


def wake_text(root: Path, plan: dict, now: float | None = None) -> str:
    """叫醒他的那段字。要在 record() 之后拼：带的是这一包存进去之后的样子。"""
    now = time.time() if now is None else now
    lines = ["🏠 [Sims 4·游戏叫你]（她没跟你说话，是游戏里出了事来叫你；这条她看不到）"]
    lines.extend(f"- {reason}" for reason in plan.get("reasons") or [])
    lines.append("")
    lines.append(_note_body(root, now))
    lines.append("她在全屏玩，多半看不到聊天窗口。" + spoken() + act_hint())
    return "\n".join(lines)


def playing_hint(root: Path, now: float | None = None) -> str:
    """她开着游戏的时候在聊天软件里说话：给 AI 一句提醒。游戏没连着就是空的。"""
    if not is_live(root, now):
        return ""
    return "她现在开着游戏在玩（全屏，很少看聊天窗口）。" + spoken()


# ───────────────────────── 小人记号：说话的同时小人就去做了 ─────────────────────────

def take_marks(text: str) -> tuple[str, list[dict]]:
    """把回话里的 ⟪小人:…⟫ 摘出来：回（她看到的正文, [要交给游戏的指令]）。
    ⟪小人:亲吻 → 小椴⟫ 去做；不写目标就是对自己；⟪小人:穿 睡衣⟫ 换衣服；⟪小人:取消⟫ 停手。"""
    marks: list[dict] = []

    def grab(match: re.Match) -> str:
        body = " ".join(match.group(1).split())
        if len(marks) >= MARKS_MAX or not body:
            return ""
        if body in ("取消", "停", "停下", "停手", "cancel"):
            marks.append({"op": "cancel", "args": {}, "label": "取消"})
        elif body.startswith(("穿", "换")) and len(body) > 1 and "→" not in body and "->" not in body:
            name = body[1:].lstrip("上成 ").strip()
            if name:
                marks.append({"op": "outfit", "args": {"name": name}, "label": f"穿 {name}"})
        else:
            parts = _ARROW_RE.split(body, maxsplit=1)
            name = parts[0].strip()
            target = parts[1].strip() if len(parts) > 1 else ""
            if name:
                args = {"name": name[:200]}
                if target:
                    args["target"] = target[:200]
                marks.append({"op": "do", "args": args, "label": f"{name} → {target}" if target else name})
        return ""

    clean = _MARK_RE.sub(grab, str(text or ""))
    if not marks:
        return str(text or ""), []
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, marks


def mark_needs_retry(result: dict) -> bool:
    """中文名头一回用，游戏那头要先去查一下名字：这种失败隔几秒再试一次就成。"""
    return not result.get("ok") and "再 do 一次" in str(result.get("text") or "")


# ───────────────────────── AI 在聊天里回的话，弹进游戏 ─────────────────────────

def log_events(root: Path, events: list[dict], now: float | None = None) -> None:
    """只记事件，不碰「游戏刚来过」的时间——不是游戏来敲门，不能把关了的游戏记成还开着。"""
    now = time.time() if now is None else now
    root.mkdir(parents=True, exist_ok=True)
    with (root / "events.jsonl").open("a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(dict(event, at=now), ensure_ascii=False) + "\n")


def mirror_pieces(root: Path, text: str, now: float | None = None) -> list[str]:
    """AI 刚在聊天里回了一句：要不要也弹进游戏、弹成几条。不弹就是空的。
    游戏连着、她在游戏世界里才弹；他刚用 say 在游戏里说过同一句就不重复。"""
    now = time.time() if now is None else now
    text = str(text or "").strip()
    if not text or not is_live(root, now) or screen(root) not in ("live", "build"):
        return []
    flat = "".join(text.split())
    for event in recent_events(root, limit=30):
        if event.get("t") != "he" or now - float(event.get("at") or 0) > MIRROR_SAME:
            continue
        said = "".join(str(event.get("text") or "").split())
        if said and (said in flat or flat in said):
            return []
    pieces, current = [], ""
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        if current and len(current) + len(para) + 1 > MIRROR_MAX:
            pieces.append(current)
            current = para
        else:
            current = f"{current}\n{para}" if current else para
    if current:
        pieces.append(current)
    pieces = [p if len(p) <= MIRROR_MAX else p[:MIRROR_MAX - 1] + "…" for p in pieces]
    if len(pieces) > MIRROR_PIECES:
        pieces = pieces[:MIRROR_PIECES - 1] + ["（后面还有，在聊天里）"]
    return pieces


def clean_photo_query(by: str, caption: str, shot: str, hold: str) -> dict:
    """转发程序传截图时带的几个小参数。"""
    if by not in ("him", "her"):
        raise ValueError("by 只能是 him / her")
    try:
        shot_id = int(shot or 0)
    except (TypeError, ValueError):
        shot_id = 0
    return {"by": by, "caption": str(caption or "").strip()[:300], "shot": shot_id,
            "hold": str(hold or "") in ("1", "true", "yes")}


def shrink_photo(data: bytes) -> bytes:
    """截图进来是几兆的 PNG：确认真是张图，缩到长边 PHOTO_EDGE，转 JPG。不是图就 ValueError。"""
    import io

    from PIL import Image

    if not data or len(data) > PHOTO_MAX_BYTES:
        raise ValueError("图太大或是空的")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise ValueError("这不是一张图")
    image = image.convert("RGB")
    image.thumbnail((PHOTO_EDGE, PHOTO_EDGE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=86)
    return out.getvalue()


def unseen_head(root: Path, now: float | None = None) -> str:
    """只靠工具来看的 AI（没接推送）：她在游戏里说了话，要等 AI 下次 look 才看得到。
    look 的时候在最上面提一句有几句没看过，然后记下「看过了」。"""
    now = time.time() if now is None else now
    looked = float((_read(root / "looked.json") or {}).get("at") or 0)
    _write(root / "looked.json", {"at": now})
    says = [e for e in recent_events(root, limit=EVENTS_KEEP)
            if e.get("t") == "say" and float(e.get("at") or 0) > looked]
    if not says:
        return ""
    lines = [f"〔她在游戏里对你说了 {len(says)} 句你还没看过的〕"]
    lines.extend(f"- {_ago(now - float(e.get('at') or now))}「{quote(e.get('text', ''))}」" for e in says[-8:])
    return "\n".join(lines)


def her_says(sync: dict) -> list[str]:
    return [e["text"] for e in sync.get("events") or [] if e.get("t") == "say" and e.get("text")]


def tell_him_note(now_text: str) -> str:
    """只给 AI 看的注解：这句话是在游戏里说的，当时什么样，怎么回。"""
    return "这句是她在游戏里对你说的。她在全屏玩，多半看不到聊天窗口。" + spoken() + act_hint() + "\n" + now_text


def tell_him_text(said: str, note: str) -> str:
    """拼好的一整段：她说的话 + 注解。只想收一段字的接法直接把这段喂给 AI。"""
    return f"🏠 [Sims 4] 她在游戏里对你说：「{quote(said)}」\n\n{note}"


def photo_text(count: int, caption: str, note: str) -> str:
    said = f"，附了一句：「{quote(caption)}」" if caption else ""
    return f"🏠 [Sims 4] 她从游戏里发来 {count} 张截图{said}\n\n{note}"
