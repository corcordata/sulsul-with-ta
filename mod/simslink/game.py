"""所有碰游戏的代码都在这里，只在游戏线程上跑。

每个读数都单独包着 try：游戏更新后哪个接口变了，只少那一项，别的照常。
接口对照的是 2026-10 的游戏脚本（1.128）。
"""
import math
import re
import sys
import time

from simslink import log, names

CONSOLE_KEYS = 'Cmd+Shift+C' if sys.platform == 'darwin' else 'Ctrl+Shift+C'    # 打开游戏输入条的键
FRIENDSHIP_TRACK = 16650
ROMANCE_TRACK = 16651
IDLE_PREFIXES = ('sim-stand', 'stand_passive', 'sim_stand', 'idle_')
MAX_LIST = 160


class OpError(Exception):
    pass


# ───────────────────────── 基本查找 ─────────────────────────

def services():
    import services as _services
    return _services


def client():
    return services().client_manager().get_first_client()


def zone_running():
    try:
        zone = services().current_zone()
        if zone is None:
            return False
        running = getattr(zone, 'is_zone_running', False)
        return bool(running() if callable(running) else running)
    except Exception:
        return False


# 游戏发出 exit2cas 之后，存档还会再跑几拍才停。所以标记不能一见存档在跑就清：
# 要等「停过一次、又跑起来」（捏完回来了），或者三分钟都没停（她取消了）。
_cas = {'pending_at': 0.0, 'seen_stop': False}
CAS_GIVE_UP = 180.0


def install_cas_watch():
    """捏人界面（CAS）是客户端自己切过去的，服务器这边只看得见「存档停了」。
    所以盯住游戏发给客户端的那条 sims.exit2cas：见到它之后存档停了，就是去捏人了。"""
    import sims4.commands as commands
    original = getattr(commands, 'client_cheat', None)
    if original is None or getattr(original, '_simslink', False):
        return

    def wrapped(text, *args, **kwargs):
        try:
            if str(text).strip().lower().startswith('sims.exit2cas'):
                _cas['pending_at'] = time.time()
                _cas['seen_stop'] = False
        except Exception:
            pass
        return original(text, *args, **kwargs)

    wrapped._simslink = True
    commands.client_cheat = wrapped


def screen():
    """她现在在哪个界面：live 游戏里 / build 建造模式 / cas 捏人 / loading 读盘 / away 主菜单或地图。"""
    try:
        zone = services().current_zone()
    except Exception:
        zone = None
    if zone is not None and zone_running():
        if _cas['pending_at'] and (_cas['seen_stop'] or time.time() - _cas['pending_at'] > CAS_GIVE_UP):
            _cas['pending_at'] = 0.0
            _cas['seen_stop'] = False
        try:
            if getattr(zone, 'is_in_build_buy', False):
                return 'build'
        except Exception:
            pass
        return 'live'
    if _cas['pending_at']:
        _cas['seen_stop'] = True
        return 'cas'
    return 'loading' if zone is not None else 'away'


def _has_cjk(text):
    return any(u'㐀' <= ch <= u'鿿' for ch in text)


def sim_name(info):
    try:
        first = (getattr(info, 'first_name', '') or '').strip()
        last = (getattr(info, 'last_name', '') or '').strip()
        if _has_cjk(first + last):
            return (last + first) or '?'
        return (first + ' ' + last).strip() or '?'
    except Exception:
        return '?'


def tuning_name(cls):
    name = getattr(cls, '__name__', None)
    return name if name else type(cls).__name__


def sim_instance(info):
    try:
        return info.get_sim_instance()
    except Exception:
        return None


def household_infos():
    try:
        household = services().active_household()
        return list(household.sim_info_gen()) if household is not None else []
    except Exception:
        return []


def active_info():
    try:
        return services().active_sim_info()
    except Exception:
        try:
            return client().active_sim_info
        except Exception:
            return None


def instanced_infos():
    """这块地上所有在场的小人（包括路人）。"""
    out = []
    try:
        for info in services().sim_info_manager().get_all():
            if sim_instance(info) is not None:
                out.append(info)
    except Exception:
        log.once('instanced', '列不出在场的小人：%s' % log.tail_error())
    return out


def find_sim(query, his_names=()):
    """按名字找小人：先全名，再包含。query 为空时找「他」。"""
    pool = household_infos()
    seen = set(id(i) for i in pool)
    for info in instanced_infos():
        if id(info) not in seen:
            pool.append(info)
    if not query:
        for key in his_names:
            for info in pool:
                if key and key.lower() in sim_name(info).lower():
                    return info
        hint = '' if his_names else '玩家还没告诉 mod 哪个小人是你：请她在游戏里按 %s，输入 ta who，照列出来的编号选一下。' % CONSOLE_KEYS
        raise OpError('没找到你的小人。%s在场的有：%s。也可以用 who 写上名字。' % (hint, '、'.join(sim_name(i) for i in pool[:12])))
    q = str(query).strip().lower()
    exact = [i for i in pool if sim_name(i).lower() == q]
    if exact:
        return exact[0]
    part = [i for i in pool if q in sim_name(i).lower() or q.replace(' ', '') in sim_name(i).lower().replace(' ', '')]
    if len(part) == 1:
        return part[0]
    if not part:
        raise OpError('没有叫「%s」的小人。在场的有：%s' % (query, '、'.join(sim_name(i) for i in pool[:12])))
    raise OpError('「%s」对得上好几个：%s' % (query, '、'.join(sim_name(i) for i in part[:8])))


# ───────────────────────── 读状态 ─────────────────────────

def _is_idle(name):
    low = name.lower()
    return any(low.startswith(p) for p in IDLE_PREFIXES)


_PART_RE = re.compile(r'^Part\((.+)\)$')
_HASH_TAIL_RE = re.compile(r'_(?=[A-Z0-9]*\d)[A-Z0-9]{8,}$')
_TAG_NOISE = ('autonomous', 'picker', 'tracker', 'cooldown', 'socialcontext')


def object_label(obj):
    """物件的名字。浴缸、床这类分「部位」的东西，报整件的名字，不报 Part(...)。"""
    owner = getattr(obj, 'part_owner', None)
    if owner is not None:
        obj = owner
    name = tuning_name(type(obj))
    match = _PART_RE.match(name)
    return match.group(1) if match else name


def clean_tags(names, limit):
    """状态 / 关系标签：去掉别的 mod 挂的随机尾巴和纯内部用的，重复的只留一个。"""
    out = []
    for name in names:
        name = _HASH_TAIL_RE.sub('', str(name).split('/')[0])
        low = name.lower()
        if not name or any(word in low for word in _TAG_NOISE):
            continue
        if name not in out:
            out.append(name)
        if len(out) >= limit:
            break
    return out


def _target_label(target):
    if target is None:
        return ''
    try:
        if getattr(target, 'is_sim', False):
            return sim_name(target.sim_info)
        return object_label(target)
    except Exception:
        return ''


def describe_interaction(interaction):
    affordance = getattr(interaction, 'affordance', None) or type(interaction)
    name = tuning_name(affordance)
    out = {'name': name}
    shown = names.label(names.key_of(affordance))
    if shown:
        out['cn'] = shown       # 她屏幕上看到的名字；name 留着内部名，服务器那头靠它认动作
    try:
        label = _target_label(getattr(interaction, 'target', None))
        if label:
            out['target'] = label
    except Exception:
        pass
    return out


def _interactions(container):
    out = []
    if container is None:
        return out
    try:
        for interaction in tuple(container):
            try:
                d = describe_interaction(interaction)
                if _is_idle(d['name']):
                    continue
                out.append(d)
            except Exception:
                continue
    except Exception:
        pass
    return out


def _motives(info):
    out = {}
    try:
        for stat in info.commodity_tracker.get_all_commodities():
            try:
                if not getattr(stat, 'is_visible', False):
                    continue
                name = tuning_name(getattr(stat, 'stat_type', None) or type(stat))
                if 'motive' not in name.lower() or ':' in name:
                    continue    # 带冒号的是别的 mod 加的数值（WW 的满足度），刻度跟游戏的需求不一样，不当需求报
                out[name.replace('motive_', '')] = int(round(stat.get_value() / 10.0) * 10)
            except Exception:
                continue
    except Exception:
        log.once('motives', '读不到需求：%s' % log.tail_error())
    return out


def _mood(info):
    try:
        mood = info.get_mood()
        if mood is None:
            return None
        out = {'name': tuning_name(mood).replace('Mood_', '')}
        try:
            out['level'] = int(info.get_mood_intensity())
        except Exception:
            pass
        return out
    except Exception:
        return None


MOOD_CN = {
    'Happy': '开心', 'Fine': '平静', 'Sad': '难过', 'Angry': '生气', 'Flirty': '调情', 'Focused': '专注',
    'Energized': '精力充沛', 'Confident': '自信', 'Inspired': '有灵感', 'Playful': '顽皮', 'Embarrassed': '尴尬',
    'Uncomfortable': '不舒服', 'Tense': '紧张', 'Bored': '无聊', 'Dazed': '恍惚', 'Scared': '害怕',
    'Asleep': '睡着', 'Possessed': '被附身',
}


def _buff_left(buff):
    """这个情绪状态还剩多少游戏分钟。没有期限、或者读不到，就 None。"""
    try:
        if getattr(buff, 'show_timeout', True) is False:
            return None
        got = buff.get_timeout_time()
        timeout = int((got[0] if isinstance(got, (tuple, list)) else got) or 0)
        if timeout <= 0:
            return None
        import date_and_time
        now = services().time_service().sim_now
        # 游戏给的多半是「到几点结束」；也可能是「还剩多久」。两种都试，只收像话的数（七天以内）
        for span in (lambda: date_and_time.DateAndTime(timeout) - now, lambda: date_and_time.TimeSpan(timeout)):
            try:
                minutes = int(span().in_minutes())
            except Exception:
                continue
            if 0 < minutes <= 7 * 24 * 60:
                return minutes
    except Exception:
        pass
    return None


def buff_cards(info):
    """小人身上每个看得见的情绪状态，照她点开看到的那张卡来读：
    名字、说明、哪种情绪加几、从哪来的、还剩多久。名字 / 说明 / 来处都只是号码，字要另查。"""
    cards = []
    try:
        buffs = list(info.Buffs)
    except Exception:
        return cards
    for buff in buffs:
        try:
            if not getattr(buff, 'visible', True):
                continue
            kind = getattr(buff, 'buff_type', None) or type(buff)
            card = {'name': tuning_name(kind), 'key': names.key_of(kind, 'buff_name'),
                    'desc': names.key_of(kind, 'buff_description')}
            mood = getattr(buff, 'mood_type', None) or getattr(kind, 'mood_type', None)
            if mood is not None:
                card['mood'] = tuning_name(mood).replace('Mood_', '')
                try:
                    weight = int(getattr(buff, 'mood_weight', 0) or getattr(kind, 'mood_weight', 0) or 0)
                except Exception:
                    weight = 0
                if weight:
                    card['w'] = weight
            reason = getattr(buff, 'buff_reason', None)
            try:
                reason_key = int(getattr(reason, 'hash', 0) or 0) & 0xFFFFFFFF if reason is not None else 0
            except Exception:
                reason_key = 0
            if reason_key:
                card['from'] = reason_key
            left = _buff_left(buff)
            if left:
                card['left'] = left
            cards.append(card)
        except Exception:
            continue
    return cards


def _buffs(info):
    """状态里带的那一份：名字 + 情绪 + 来处 + 还剩多久（说明太长，他要看再用 moodlets 单独要）。"""
    out, seen = [], set()
    for card in buff_cards(info):
        title = names.label(card['key'])
        if not title:
            kept = clean_tags([card['name']], 1)      # 没有名字的：内部名里纯内部用的那些直接不报
            if not kept:
                continue
            title = kept[0]
        if title in seen:
            continue
        seen.add(title)
        row = {'t': title}
        if card.get('mood'):
            row['mood'] = card['mood']
        if card.get('w'):
            row['w'] = card['w']
        source = names.label(card.get('from'))
        if source:
            row['from'] = source
        if card.get('left'):
            row['left'] = card['left']
        out.append(row)
        if len(out) >= 10:
            break
    return out


def span_text(minutes):
    minutes = int(minutes)
    if minutes >= 24 * 60:
        return '%d 天 %d 小时' % (minutes // 1440, (minutes % 1440) // 60)
    if minutes >= 60:
        return '%d 小时 %d 分' % (minutes // 60, minutes % 60)
    return '%d 分钟' % minutes


def show_buff_cards(cards):
    """moodlets 用：每个状态一张完整的卡。"""
    lines = []
    for card in cards:
        title = names.label(card['key']) or card['name']
        bits = []
        if card.get('mood'):
            mood = MOOD_CN.get(card['mood'], card['mood'])
            bits.append('%s +%d' % (mood, card['w']) if card.get('w') else mood)
        source = names.label(card.get('from')).strip('（）() ')
        if source.startswith('来自'):            # 游戏里这句本身就写着「（来自……）」
            source = source[2:].strip('：: ')
        if source:
            bits.append('来自 ' + source)
        if card.get('left'):
            bits.append('还剩 ' + span_text(card['left']))
        lines.append('【%s】%s' % (title, '｜'.join(bits)))
        explain = names.label(card.get('desc'))
        if explain:
            lines.append('  ' + explain)
    return lines


def _pregnant(info):
    try:
        tracker = info.pregnancy_tracker
        value = tracker.is_pregnant
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _track(track_id):
    try:
        import sims4.resources
        return services().get_instance_manager(sims4.resources.Types.STATISTIC).get(track_id)
    except Exception:
        return None


def _relationship(info, other):
    out = {}
    try:
        tracker = info.relationship_tracker
        other_id = other.sim_id
        if not tracker.has_relationship(other_id):
            return out
        for key, track_id in (('friend', FRIENDSHIP_TRACK), ('romance', ROMANCE_TRACK)):
            try:
                track = _track(track_id)
                if track is not None:
                    out[key] = int(round(tracker.get_relationship_score(other_id, track=track)))
            except Exception:
                continue
        try:
            bits = [tuning_name(b) for b in tracker.get_all_bits(target_sim_id=other_id)]
            keep = [b for b in bits if not b.lower().startswith(('shorttermbits', 'relbit_trope'))]
            out['bits'] = clean_tags(keep, 10)
        except Exception:
            pass
    except Exception:
        pass
    return out


def _distance(a, b):
    try:
        pa, pb = a.position, b.position
        return math.sqrt((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2 + (pa.z - pb.z) ** 2)
    except Exception:
        return None


def _on_this_lot(sim, household_sims):
    """这个小人是不是真站在这块地上（屋里、院子里）。三种问法，一种不灵换下一种。"""
    try:
        return bool(services().current_zone().lot.is_position_on_lot(sim.position))
    except Exception:
        log.once('lot_pos', '问不了 lot.is_position_on_lot，换 sim.is_on_active_lot：%s' % log.tail_error())
    try:
        return bool(sim.is_on_active_lot())
    except Exception:
        log.once('lot_sim', '问不了 sim.is_on_active_lot，改用离家里人的距离：%s' % log.tail_error())
    for _info, mine in household_sims:
        dist = _distance(sim, mine)
        if dist is not None and dist <= 12.0:
            return True
    return False


def _zone_info():
    out = {}
    try:
        zone = services().current_zone()
        zone_id = zone.id
        try:
            proto = services().get_persistence_service().get_zone_proto_buff(zone_id)
            if proto is not None and proto.name:
                out['lot'] = proto.name
        except Exception:
            pass
        try:
            venue = services().venue_service().get_venue_tuning(zone_id)
            if venue is not None:
                out['venue'] = tuning_name(venue)
        except Exception:
            pass
        try:
            household = services().active_household()
            out['home'] = bool(household is not None and household.home_zone_id == zone_id)
        except Exception:
            pass
    except Exception:
        pass
    return out


def _clock():
    out = {}
    try:
        now = services().time_service().sim_now
        out = {'day': int(now.day()), 'hour': int(now.hour()), 'minute': int(now.minute())}
    except Exception:
        pass
    try:
        speed = services().game_clock_service().clock_speed
        out['speed'] = getattr(speed, 'name', str(speed))
    except Exception:
        pass
    return out


# ───────────────────────── 衣服 · 钱 ─────────────────────────

# (游戏里的类别名, 给他看的名字, 他可以怎么叫它)
OUTFITS = (
    ('EVERYDAY', '日常', ('everyday', '便服', '平时')),
    ('FORMAL', '正装', ('formal', '礼服', '西装')),
    ('ATHLETIC', '运动', ('athletic', '健身', '运动服')),
    ('SLEEP', '睡衣', ('sleep', 'sleepwear', '睡觉')),
    ('PARTY', '派对', ('party', '聚会')),
    ('SWIMWEAR', '泳装', ('swim', 'swimwear', '泳衣', '泳裤')),
    ('HOTWEATHER', '热天', ('hot', 'hotweather', '夏天')),
    ('COLDWEATHER', '冷天', ('cold', 'coldweather', '冬天')),
    ('BATHING', '不穿', ('bathing', 'nude', 'naked', '裸', '脱光', '洗澡')),
)
_OUTFIT_CN = dict((key, cn) for key, cn, _alias in OUTFITS)
# 这几类他自己换不了，但会被游戏或别的 mod 换上，看得懂就行
_OUTFIT_CN.update({'CAREER': '工作服', 'SITUATION': '场合装', 'SPECIAL': '特殊装', 'BATHING': '不穿'})
MAX_OUTFITS = 5


def _outfit_category(key):
    from sims.outfits.outfit_enums import OutfitCategory
    return getattr(OutfitCategory, key)


def current_outfit(info):
    """现在穿的是哪一套，写成「睡衣 1」。读不到就给空的。"""
    try:
        category, index = info.get_current_outfit()
        key = getattr(category, 'name', None)
        if key is None:
            from sims.outfits.outfit_enums import OutfitCategory
            key = OutfitCategory(int(category)).name
        return '%s %d' % (_OUTFIT_CN.get(key, key), int(index) + 1)
    except Exception:
        return ''


def _outfit_count(info, key):
    category = _outfit_category(key)
    count = 0
    for index in range(MAX_OUTFITS):
        try:
            if not info.has_outfit((category, index)):
                break
        except Exception:
            break
        count += 1
    return count


def list_outfits(info):
    rows = []
    for key, cn, _alias in OUTFITS:
        try:
            count = _outfit_count(info, key)
        except Exception:
            count = 0
        if count:
            rows.append('%s（%d 套）' % (cn, count) if count > 1 else cn)
    return rows


def change_outfit(info, text):
    """text：「睡衣」「正装 2」「不穿」。换好了回一句给他看的话。"""
    text = str(text or '').strip()
    number = 1
    parts = text.split()
    if parts and parts[-1].isdigit():
        number = int(parts[-1])
        text = ' '.join(parts[:-1]).strip()
    low = text.lower()
    chosen = None
    for key, cn, alias in OUTFITS:
        if low and (low == cn or low == key.lower() or low in alias or cn in low or any(a in low for a in alias)):
            chosen = (key, cn)
            break
    if chosen is None:
        raise OpError('没有「%s」这类衣服。你有：%s。现在穿着 %s。'
                      % (text, '、'.join(list_outfits(info)) or '（读不到）', current_outfit(info) or '？'))
    key, cn = chosen
    count = _outfit_count(info, key)
    if count == 0:
        raise OpError('你没有「%s」这类衣服（她没给你捏）。你有：%s。' % (cn, '、'.join(list_outfits(info))))
    if number < 1 or number > count:
        raise OpError('「%s」只有 %d 套，写 1 到 %d。' % (cn, count, count))
    wanted = (_outfit_category(key), number - 1)
    label = '%s %d' % (cn, number)
    if current_outfit(info) == label:
        return '你本来就穿着 %s。' % label
    try:
        info.set_current_outfit(wanted)
    except Exception:
        log.once('outfit_set', 'set_current_outfit 不灵，换 try_set_current_outfit：%s' % log.tail_error())
    if current_outfit(info) != label:
        try:
            info.try_set_current_outfit(wanted, do_spin=True)
        except Exception:
            log.once('outfit_try', 'try_set_current_outfit 也不灵：%s' % log.tail_error())
    now = current_outfit(info)
    if now and now != label:
        raise OpError('没换成，还穿着 %s。游戏没让换（可能正在洗澡、上班，或者做到一半）。' % now)
    return '换好了：%s。' % label


def household_funds():
    try:
        return int(services().active_household().funds.money)
    except Exception:
        return None


def give_money(amount):
    """往家里的存款里加钱；回加完之后的数。"""
    household = services().active_household()
    if household is None:
        raise OpError('现在没有在玩的家庭。')
    reason = 0
    try:
        from protocolbuffers import Consts_pb2
        reason = getattr(Consts_pb2, 'TELEMETRY_MONEY_CHEAT', 0)
    except Exception:
        pass
    household.funds.add(int(amount), reason, None)
    return household_funds()


def _fire_active():
    try:
        return bool(services().get_fire_service().fire_is_active)
    except Exception:
        return False


def snapshot(his_names=(), her_names=()):
    """一张现在的样子。里面没有会每秒变的小数，方便比较「变没变」。"""
    household = household_infos()
    active = active_info()
    sims = []
    present = []
    for info in household:
        sim = sim_instance(info)
        name = sim_name(info)
        entry = {'name': name, 'here': sim is not None}
        if any(k and k.lower() in name.lower() for k in his_names):
            entry['his'] = True
        elif any(k and k.lower() in name.lower() for k in her_names):
            entry['hers'] = True
        try:
            if getattr(info, 'is_dead', False):
                entry['dead'] = True
        except Exception:
            pass
        if active is not None and info is active:
            entry['active'] = True
        mood = _mood(info)
        if mood:
            entry['mood'] = mood
        motives = _motives(info)
        if motives:
            entry['motives'] = motives
        if _pregnant(info):
            entry['pregnant'] = True
        buffs = _buffs(info)
        if buffs:
            entry['buffs'] = buffs
        if sim is not None:
            present.append((info, sim))
            outfit = current_outfit(info)
            if outfit:
                entry['outfit'] = outfit
            entry['doing'] = _interactions(getattr(sim, 'si_state', None))
            entry['queue'] = _interactions(getattr(sim, 'queue', None))
        rel = {}
        for other in household:
            if other is info:
                continue
            r = _relationship(info, other)
            if r:
                rel[sim_name(other)] = r
        if rel:
            entry['rel'] = rel
        sims.append(entry)
    # 家里人以外的小人：游戏把整条街的路人都载进来了，得分清谁真在这块地上、谁只是路过。
    household_ids = set(id(i) for i in household)
    on_lot, street = [], []
    for info in instanced_infos():
        if id(info) in household_ids:
            continue
        other_sim = sim_instance(info)
        (on_lot if _on_this_lot(other_sim, present) else street).append((info, other_sim))
    for entry, (info, sim) in zip([s for s in sims if s['here']], present):
        near = []
        for other_info, other_sim in present + on_lot + street:
            if other_sim is sim:
                continue
            dist = _distance(sim, other_sim)
            if dist is not None and dist <= 4.0:
                near.append(sim_name(other_info))
        if near:
            entry['near'] = near
    out = {'zone': _zone_info(), 'clock': _clock(), 'sims': sims,
           'others': [sim_name(i) for i, _sim in on_lot][:14],
           'street': {'n': len(street), 'names': [sim_name(i) for i, _sim in street][:6]}}
    funds = household_funds()
    if funds is not None:
        out['funds'] = funds
    if _fire_active():
        out['fire'] = True
    return out


# ───────────────────────── 说话 ─────────────────────────

def _raw(text):
    from sims4.localization import LocalizationHelperTuning
    return LocalizationHelperTuning.get_raw_text(text)


def notify(title, text, icon_sim=None):
    """右上角弹一条消息；icon_sim 给了就用那个小人的头像。"""
    from ui.ui_dialog_notification import UiDialogNotification
    title_ls, text_ls = _raw(title), _raw(text)
    dialog = UiDialogNotification.TunableFactory().default(
        None, title=lambda *_, **__: title_ls, text=lambda *_, **__: text_ls)
    icon = None
    if icon_sim is not None:
        try:
            from distributor.shared_messages import IconInfoData
            icon = IconInfoData(obj_instance=icon_sim)
        except Exception:
            icon = None
    dialog.show_dialog(icon_override=icon)


_INPUT_NAME = 'text_input'
_input_cls = None


def _input_dialog_class():
    global _input_cls
    if _input_cls is not None:
        return _input_cls
    from ui.ui_dialog_generic import UiDialogTextInputOkCancel

    class SimsLinkTextInput(UiDialogTextInputOkCancel):
        def on_text_input(self, text_input_name='', text_input=''):
            # 返回 True = 收下了。返回 False 的话游戏会在控制台印一行
            # 「Unable to set dialog text input…」，字其实已经收到，只是看着像出错。
            self.text_input_responses[text_input_name] = text_input
            return True

        def build_msg(self, text_input_overrides=None, additional_tokens=(), **kwargs):
            msg = super().build_msg(additional_tokens=(), **kwargs)
            field = msg.text_input.add()
            field.text_input_name = _INPUT_NAME
            return msg

    _input_cls = SimsLinkTextInput
    return _input_cls


def ask(title, text, on_answer, on_close=None):
    """弹一个能打字的框；她点确定后 on_answer(她打的字)。取消就不回调。
    on_close 不管确定还是取消，框一关就叫（用来把输入法切回去）。"""
    cls = _input_dialog_class()
    title_ls, text_ls = _raw(title), _raw(text)
    owner = active_info()
    dialog = cls.TunableFactory().default(owner, title=lambda *_, **__: title_ls, text=lambda *_, **__: text_ls)

    def _done(dlg):
        if on_close is not None:
            try:
                on_close()
            except Exception:
                log.once('ask_close', '输入框关了之后的收尾出错：%s' % log.tail_error())
        try:
            if not dlg.accepted:
                return
            value = dlg.text_input_responses.get(_INPUT_NAME)
            value = (str(value) if value is not None else '').strip()
            if value:
                on_answer(value)
        except Exception:
            log.exception('输入框回调出错')

    dialog.add_listener(_done)
    dialog.show_dialog()


# ───────────────────────── 动作 ─────────────────────────

def _context(sim, target=None):
    pick = None
    if target is not None:
        try:
            from server.pick_info import PickInfo, PickType
            pick_type = PickType.PICK_SIM if getattr(target, 'is_sim', False) else PickType.PICK_OBJECT
            pick = PickInfo(pick_type=pick_type, target=target, location=target.position,
                            routing_surface=target.routing_surface)
        except Exception:
            pick = None
    try:
        if pick is not None:
            return client().create_interaction_context(sim, pick=pick)
        return client().create_interaction_context(sim)
    except Exception:
        from interactions.context import InteractionContext
        from interactions.priority import Priority
        return InteractionContext(sim, InteractionContext.SOURCE_PIE_MENU, Priority.High)


def _potential_aops(sim, target, context, phone=False):
    """跟她点一下出来的菜单同一套来源：物件/小人自己的动作 + 展开的社交小项。"""
    if phone:
        base = list(sim.potential_phone_interactions(context))
    else:
        base = list(target.potential_interactions(context))
    out = []
    for aop in base:
        out.append((aop, None))
        try:
            subs = aop.affordance.potential_pie_menu_sub_interactions_gen(
                aop.target, context, None, **aop.interaction_parameters)
            for mixer_aop, mixer_result in subs:
                out.append((mixer_aop, mixer_result))
        except Exception:
            log.once('subs', '展开社交小项出错（只影响聊天类动作）：%s' % log.tail_error())
    if not phone and target is not None and getattr(target, 'is_sim', False) and target is not sim:
        # 已经在跟对方聊的时候，接下来能说的那些
        try:
            from autonomy import content_sets
            for si in tuple(sim.si_state):
                try:
                    content = content_sets.generate_content_set(
                        sim, si.super_affordance, si, context, potential_targets=(target,))
                    for _weight, aop, test_result in content:
                        out.append((aop, test_result))
                except Exception:
                    continue
        except Exception:
            pass
    return out


def _usable(aop, context, preset):
    try:
        if getattr(aop.affordance, 'allow_user_directed', True) is False:
            return False
    except Exception:
        pass
    try:
        result = preset if preset is not None else aop.test(context)
        return bool(result)
    except Exception:
        return False


def resolve_target(sim, target, his_names=()):
    """target：'self' / 'phone' / 小人名字 / 物件编号 / 物件名字的一部分（取最近的）。"""
    if target in (None, '', 'self', '自己'):
        return sim, False
    if str(target).lower() in ('phone', '手机'):
        return sim, True
    text = str(target).strip()
    if text.isdigit():
        obj = services().object_manager().get(int(text))
        if obj is None:
            raise OpError('没有编号 %s 的东西（可能被搬走了），重新 objects 看一下。' % text)
        return obj, False
    try:
        info = find_sim(text)
    except OpError as exc:
        info, sim_error = None, exc
    if info is not None:
        other = sim_instance(info)
        if other is None:
            raise OpError('%s 不在这块地上，碰不到。' % sim_name(info))
        return other, False
    best, best_dist = None, None
    for obj in _lot_objects():
        if text.lower() in tuning_name(type(obj)).lower():
            dist = _distance(sim, obj)
            if best is None or (dist is not None and (best_dist is None or dist < best_dist)):
                best, best_dist = obj, dist
    if best is None:
        raise OpError('%s 也没有名字带「%s」的东西。' % (sim_error, text))
    return best, False


def list_interactions(sim, target, phone=False):
    """现在能做的动作：[(内部名, 名字号码)]。名字号码拿去查她屏幕上显示的那个名字。"""
    context = _context(sim, None if phone else target)
    rows, seen = [], set()
    for aop, preset in _potential_aops(sim, target, context, phone=phone):
        try:
            name = tuning_name(aop.affordance)
        except Exception:
            continue
        if name in seen or _is_idle(name):
            continue
        if not _usable(aop, context, preset):
            continue
        seen.add(name)
        rows.append((name, names.key_of(aop.affordance)))
    return rows


def show_interactions(rows, flt=''):
    """把 list_interactions 的结果写成给他看的名字：有中文用中文，重名的后面带上内部名。"""
    flt = str(flt or '').strip().lower()
    picked = []
    for name, key in rows:
        shown = names.label(key)
        if flt and flt not in name.lower() and flt not in shown.lower():
            continue
        picked.append((name, shown))
    count = {}
    for _name, shown in picked:
        count[shown] = count.get(shown, 0) + 1
    out = []
    for name, shown in picked:
        if not shown:
            out.append(name)
        elif count[shown] > 1:
            out.append('%s · %s' % (shown, name))
        else:
            out.append(shown)
    return out


def do_interaction(sim, target, name, phone=False):
    context = _context(sim, None if phone else target)
    wanted = str(name).strip().lower()
    if ' · ' in wanted:                      # list 里重名的写成「聊天 · sim_Chat」：认后面的内部名
        wanted = wanted.split(' · ')[-1].strip()
    exact, partial, unknown = [], [], []
    for aop, preset in _potential_aops(sim, target, context, phone=phone):
        try:
            aop_name = tuning_name(aop.affordance)
        except Exception:
            continue
        key = names.key_of(aop.affordance)
        shown = names.label(key)
        if key and not shown:
            unknown.append(key)
        label = shown or aop_name
        low = aop_name.lower()
        if low == wanted or (shown and shown.lower() == wanted):
            exact.append((aop, preset, label))
        elif wanted in low or (shown and wanted in shown.lower()):
            partial.append((aop, preset, label))
    pool = exact or partial
    if not pool:
        if unknown and _has_cjk(wanted):
            raise OpError('「%s」这个名字刚去查了，过两三秒再 do 一次就认得了（或者先 list）。' % name)
        raise OpError('这里没有叫「%s」的动作。先 list 看看能做什么。' % name)
    if not exact:
        distinct = sorted(set(p[2] for p in partial))
        if len(distinct) > 1:
            raise OpError('「%s」对得上好几个，写全名：%s' % (name, '、'.join(distinct[:12])))
    last_reason = ''
    for aop, preset, aop_name in pool:
        if not _usable(aop, context, preset):
            try:
                last_reason = str(aop.test(context))
            except Exception:
                last_reason = '现在做不了'
            continue
        result = aop.test_and_execute(context)
        if result:
            return aop_name
        last_reason = str(result)
    raise OpError('「%s」现在做不了：%s' % (pool[0][2], last_reason or '条件不满足'))


def cancel_all(sim):
    from interactions.interaction_finisher import FinishingType
    count = 0
    for container in (getattr(sim, 'queue', None), getattr(sim, 'si_state', None)):
        if container is None:
            continue
        for interaction in tuple(container):
            try:
                name = tuning_name(getattr(interaction, 'affordance', None) or type(interaction))
                if _is_idle(name):
                    continue
                interaction.cancel(FinishingType.USER_CANCEL, cancel_reason_msg='SimsLink')
                count += 1
            except Exception:
                continue
    return count


def _lot_objects():
    out = []
    try:
        for obj in services().object_manager().values():
            try:
                if getattr(obj, 'is_sim', False):
                    continue
                if not obj.is_on_active_lot():
                    continue
                out.append(obj)
            except Exception:
                continue
    except Exception:
        log.once('objects', '列不出物件：%s' % log.tail_error())
    return out


def list_objects(sim, flt=''):
    """这块地上的东西，同一种只留离他最近的那个。"""
    nearest = {}
    for obj in _lot_objects():
        name = tuning_name(type(obj))
        if flt and flt.lower() not in name.lower():
            continue
        dist = _distance(sim, obj)
        current = nearest.get(name)
        if current is None or (dist is not None and (current[0] is None or dist < current[0])):
            nearest[name] = (dist, obj)
    rows = sorted(nearest.items(), key=lambda kv: (kv[1][0] is None, kv[1][0] or 0))
    out = []
    for name, (dist, obj) in rows[:80]:
        row = {'id': int(obj.id), 'name': name}
        if dist is not None:
            row['m'] = int(round(dist))
        out.append(row)
    return out


def set_speed(mode):
    from clock import ClockSpeedMode
    table = {'pause': ClockSpeedMode.PAUSED, '0': ClockSpeedMode.PAUSED, '1': ClockSpeedMode.NORMAL,
             '2': ClockSpeedMode.SPEED2, '3': ClockSpeedMode.SPEED3}
    key = str(mode).strip().lower()
    if key not in table:
        raise OpError('speed 只能是 pause / 1 / 2 / 3')
    services().game_clock_service().set_clock_speed(table[key])
    return key


def now_ms():
    return int(time.time() * 1000)
