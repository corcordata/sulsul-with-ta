"""游戏线程上的泵：每一拍看看他有没有指令，每两秒看一眼游戏变没变。"""
import json
import threading
import time

from sulsul import game, log, names
from sulsul.net import Link

SNAP_EVERY = 2.0        # 秒，真实时间
RESEND_EVERY = 30.0     # 没变化也隔一阵报一次，服务器好知道「还在玩」
MAX_CMDS_PER_TICK = 4

link = None
cfg = {}
_state = {'last_snap': 0.0, 'last_sent': 0.0, 'last_key': '', 'prev': None, 'busy': False, 'was_running': False,
          'force': False, 'screen': None, 'asking': 0.0}

NOT_IN_WORLD = {
    'cas': '她在捏人界面，游戏世界停着，小人动不了。等她捏完回来。',
    'loading': '游戏在读盘，等一下。',
    'away': '她不在存档里（主菜单或地图）。',
}
NO_PHOTO = {
    'cas': '她在捏人界面，镜头里不是游戏世界，现在拍不了。等她捏完回来再拍。',
    'loading': '游戏在读盘，拍不了，等一下。',
    'away': '她不在存档里（主菜单或地图），拍不了。',
}


_later = []


def later(fn):
    """后台线程办完事，想在游戏线程上做点什么（弹通知），丢到这里，下一拍执行。"""
    _later.append(fn)


def _background(fn):
    worker = threading.Thread(target=fn, name='SulSulJob')
    worker.daemon = True
    worker.start()


def his_names():
    """TA 的小人叫什么（名字里带这些字的那个）。"""
    return [str(n) for n in (cfg.get('ta_names') or []) if n]


def her_names():
    """玩家自己的小人叫什么。"""
    return [str(n) for n in (cfg.get('player_names') or []) if n]


def set_names(which, names):
    """ta ta 编号 / ta me 编号：记进 SulSul.cfg，当场生效。"""
    cfg[which] = list(names)
    log.save_config({which: list(names)})
    _state['force'] = True


# ───────────────────────── 她在游戏里说话 ─────────────────────────

def her_say(text):
    if link is None:
        return False
    link.push_event({'t': 'say', 'text': str(text)[:1000], 'at': game.now_ms()})
    _state['force'] = True
    return True


def _ime(chinese):
    """请小转发程序把输入法切到中文 / 英文。中文输入法开着的时候 WASD 会被它吃掉，
    所以平时停在英文，只有输入框开着的那一会儿是中文。cfg 里 "auto_ime": false 可以关掉。"""
    if link is None or cfg.get('auto_ime', True) is False:
        return
    _background(lambda: link.local('/local/ime', {'on': bool(chinese)}, timeout=5))


def ask_her(title, text, on_answer=None):
    """弹出能打字的框。她打的字默认当成对他说的话。"""
    def _closed():
        _state['asking'] = 0.0
        _ime(False)

    game.ask(title, text, on_answer or her_say, on_close=_closed)
    _state['asking'] = time.time()
    _ime(True)


def _hotkey_talk():
    # 框已经开着就不叠第二个；两分钟还没关多半是丢了，放行
    if time.time() - _state['asking'] < 120:
        return
    ask_her('跟 TA 说', '想跟 TA 说什么？')


def _key_loop():
    """后台线程：在小转发程序那儿等她按说话快捷键。旧版转发程序不认识这个请求，隔一阵再问。"""
    while True:
        try:
            reply = link.local('/local/wait', {}, timeout=40)
            if reply.get('ok') and reply.get('text') == 'talk':
                later(_hotkey_talk)
            elif reply.get('ok') and reply.get('text') == 'boss':
                later(_boss)
            elif not reply.get('ok'):
                time.sleep(20)
        except Exception:
            time.sleep(20)


def _boss():
    """老板键：窗口和声音小转发程序已经藏好了，这里把游戏暂停，免得小人背着她继续。"""
    try:
        if game.zone_running():
            game.set_speed('pause')
    except Exception:
        log.once('boss', '老板键暂停游戏没成：%s' % log.tail_error())


def her_key(name, which='talk'):
    """ta key F9：换说话快捷键；ta boss F10：换老板键；不带键名就是看现在是哪个。"""
    def job():
        reply = link.local('/local/key', {'key': name, 'which': which}, timeout=5)
        text = reply.get('text') or '没换成'
        later(lambda: game.notify('Sul Sul', text))

    _background(job)


def her_wake(on):
    """ta wake on / off：游戏里出了事要不要去叫 AI。记在服务器那头。"""
    if link is not None:
        link.push_event({'t': 'wake', 'on': bool(on), 'at': game.now_ms()})


# ───────────────────────── 他的指令 ─────────────────────────

def _his_sim(args):
    info = game.find_sim(args.get('who') or '', his_names())
    sim = game.sim_instance(info)
    if sim is None:
        raise game.OpError('%s 不在这块地上，动不了。' % game.sim_name(info))
    return info, sim


def _op_say(args):
    text = str(args.get('text') or '').strip()
    if not text:
        raise game.OpError('text 是空的')
    title, icon = 'TA', None
    try:
        info = game.find_sim(args.get('who') or '', his_names())
        title = game.sim_name(info)
        icon = game.sim_instance(info)
    except game.OpError:
        pass
    if args.get('reply'):
        ask_her(title, text)
        return '问出去了，输入框开在她屏幕上。'
    game.notify(title, text, icon)
    return '她屏幕右上角弹出来了。'


MAX_GIFT = 50000


def _op_outfit(args):
    info, _sim = _his_sim(args)
    wanted = str(args.get('name') or '').strip()
    if not wanted:
        return '%s 现在穿着 %s。能换的：%s。' % (game.sim_name(info), game.current_outfit(info) or '？',
                                           '、'.join(game.list_outfits(info)) or '（读不到）')
    done = game.change_outfit(info, wanted)
    _state['force'] = True
    return done


def _op_money(args):
    try:
        amount = int(float(args.get('amount') or 0))
    except (TypeError, ValueError):
        amount = 0
    if amount < 1 or amount > MAX_GIFT:
        raise game.OpError('amount 写 1 到 %d 之间的整数。' % MAX_GIFT)
    title, icon = 'TA', None
    try:
        info = game.find_sim(args.get('who') or '', his_names())
        title, icon = game.sim_name(info), game.sim_instance(info)
    except game.OpError:
        pass
    total = game.give_money(amount)
    note = str(args.get('text') or '').strip()
    game.notify(title, '给你转了 §%s%s' % (format(amount, ','), ('：' + note) if note else ''), icon)
    _state['force'] = True
    return '转过去了 §%s，她屏幕右上角看得到。家里现在有 §%s。' % (
        format(amount, ','), format(total, ',') if total is not None else '？')


def _list_text(who, rows, flt):
    shown = game.show_interactions(rows, flt)
    if not shown:
        return '这里现在没有能做的（或者筛得太窄）。'
    more = ''
    if len(shown) > game.MAX_LIST:
        more = '\n……还有 %d 个，用 filter 缩小。' % (len(shown) - game.MAX_LIST)
        shown = shown[:game.MAX_LIST]
    return '%s 能做的（%d 个）：\n%s%s' % (who, len(shown), '\n'.join(shown), more)


def _start_moodlets(cid, args):
    """小人身上的情绪状态，照她点开看到的那张卡念给他。字要问小转发程序，所以结果由后台交。"""
    who = str(args.get('who') or '').strip()
    if who:
        infos = [game.find_sim(who, his_names())]
    else:
        infos = [i for i in game.household_infos() if game.sim_instance(i) is not None][:4]
    packs = [(game.sim_name(info), game.buff_cards(info)) for info in infos]
    keys = [card[k] for _name, cards in packs for card in cards for k in ('key', 'desc', 'from') if card.get(k)]

    def finish():
        lines = []
        for name, cards in packs:
            lines.append('%s：' % name)
            lines.extend(game.show_buff_cards(cards) or ['  身上没有情绪状态。'])
        link.push_result({'id': cid, 'ok': True, 'text': '\n'.join(lines) or '没有在场的小人。'})

    if not names.missing(keys):
        finish()
        return

    def job():
        try:
            names.fetch(link, keys, timeout=10)
        except Exception:
            log.once('names', '查名字出错（先用内部名）：%s' % log.tail_error())
        finish()

    _background(job)


def her_ime(on):
    """ta ime off：输入框弹出来时别替我切中文（想打英文的时候）；ta ime on 恢复。记进 SulSul.cfg。"""
    cfg['auto_ime'] = bool(on)
    log.save_config({'auto_ime': bool(on)})


def _start_list(cid, args):
    """列能做的动作。动作在游戏里的名字（中文）要问小转发程序，头一回要等一两秒，所以结果由后台交。"""
    info, sim = _his_sim(args)
    target, phone = game.resolve_target(sim, args.get('target'), his_names())
    rows = game.list_interactions(sim, target, phone=phone)
    who, flt = game.sim_name(info), str(args.get('filter') or '')
    keys = [key for _name, key in rows]

    def finish():
        link.push_result({'id': cid, 'ok': True, 'text': _list_text(who, rows, flt)})

    if not names.missing(keys):
        finish()
        return

    def job():
        try:
            names.fetch(link, keys, timeout=10)
        except Exception:
            log.once('names', '查动作的名字出错（先用内部名）：%s' % log.tail_error())
        finish()

    _background(job)


def _op_do(args):
    info, sim = _his_sim(args)
    name = args.get('name')
    if not name:
        raise game.OpError('name 是空的：写上 list 里的动作名')
    target, phone = game.resolve_target(sim, args.get('target'), his_names())
    done = game.do_interaction(sim, target, name, phone=phone)
    _state['force'] = True
    return '%s 排上了：%s' % (game.sim_name(info), done)


def _op_objects(args):
    info, sim = _his_sim(args)
    rows = game.list_objects(sim, flt=str(args.get('filter') or ''))
    if not rows:
        return '这块地上没找到东西（或者筛得太窄）。'
    lines = ['%s  #%s%s' % (r['name'], r['id'], ('  %dm' % r['m']) if 'm' in r else '') for r in rows]
    return '这块地上的东西（离 %s 近的在前，同一种只列最近的）：\n%s' % (game.sim_name(info), '\n'.join(lines))


def _op_cancel(args):
    info, sim = _his_sim(args)
    count = game.cancel_all(sim)
    _state['force'] = True
    return '%s 手上和排队的 %d 件事都取消了。' % (game.sim_name(info), count)


def _op_speed(args):
    return '游戏速度改成 %s 了。' % game.set_speed(args.get('speed'))


def _start_photo(cid, args):
    """AI 说「拍一张」：让小转发程序去按截图键、把图传给服务器。要等几秒，放后台线程。"""
    caption = str(args.get('text') or '').strip()
    sims_dir = log.sims_dir()

    def job():
        answer = link.local('/local/shoot', {'shot': cid, 'caption': caption, 'dir': sims_dir}, timeout=40)
        link.push_result({'id': cid, 'ok': bool(answer.get('ok')), 'text': str(answer.get('text') or '')})

    _background(job)


def her_pictures(count, caption=''):
    """玩家在控制台打 ta pic：把最新的几张截图发给 AI。"""
    sims_dir = log.sims_dir()

    def job():
        answer = link.local('/local/send', {'count': count, 'caption': caption, 'dir': sims_dir}, timeout=90)
        text = str(answer.get('text') or '')
        later(lambda: game.notify('Sul Sul', text))

    _background(job)


def her_auto_share(on):
    sims_dir = log.sims_dir()

    def job():
        answer = link.local('/local/auto', {'on': bool(on), 'dir': sims_dir}, timeout=10)
        text = str(answer.get('text') or '')
        later(lambda: game.notify('Sul Sul', text))

    _background(job)


OPS = {'say': _op_say, 'do': _op_do, 'objects': _op_objects, 'cancel': _op_cancel,
       'outfit': _op_outfit, 'money': _op_money,
       'speed': _op_speed}


def _run_command(cmd):
    cid = cmd.get('id')
    op = str(cmd.get('op') or '')
    args = cmd.get('args') or {}
    try:
        if op == 'photo':
            if not game.zone_running():
                raise game.OpError(NO_PHOTO.get(game.screen(), '游戏还没进到存档里，拍不了。'))
            _start_photo(cid, args)       # 结果由后台线程交
            return
        if op in ('list', 'moodlets'):
            if not game.zone_running():
                raise game.OpError(NOT_IN_WORLD.get(game.screen(), '游戏还没进到存档里。'))
            (_start_list if op == 'list' else _start_moodlets)(cid, args)   # 结果由后台线程交（可能要先查名字）
            return
        if op not in OPS:
            raise game.OpError('这个版本的 mod 不认识「%s」' % op)
        if op != 'say' and not game.zone_running():
            raise game.OpError(NOT_IN_WORLD.get(game.screen(), '游戏还没进到存档里。'))
        text = OPS[op](args)
        link.push_result({'id': cid, 'ok': True, 'text': text})
    except game.OpError as exc:
        link.push_result({'id': cid, 'ok': False, 'text': str(exc)})
    except Exception:
        log.exception('指令 %s 出错' % op)
        link.push_result({'id': cid, 'ok': False, 'text': '游戏里出错了：%s' % log.tail_error()})


# ───────────────────────── 看游戏变没变 ─────────────────────────

def _lead(entry):
    doing = entry.get('doing') or []
    return doing[-1] if doing else None


def _diff_events(prev, cur):
    events = []
    if prev is None:
        return events
    if (prev.get('zone') or {}).get('lot') != (cur.get('zone') or {}).get('lot'):
        events.append({'t': 'zone', 'zone': cur.get('zone') or {}})
    if bool(prev.get('fire')) != bool(cur.get('fire')):
        events.append({'t': 'fire', 'on': bool(cur.get('fire'))})
    before = dict((s['name'], s) for s in prev.get('sims') or [])
    for sim in cur.get('sims') or []:
        old = before.get(sim['name'])
        if old is None:
            continue
        lead, old_lead = _lead(sim), _lead(old)
        # 只比动作和目标：中文名是后来才查到的，它到了不算「换了件事」
        if lead and (lead.get('name'), lead.get('target')) != ((old_lead or {}).get('name'), (old_lead or {}).get('target')):
            event = {'t': 'act', 'who': sim['name'], 'name': lead['name']}
            if lead.get('cn'):
                event['cn'] = lead['cn']
            if lead.get('target'):
                event['target'] = lead['target']
            events.append(event)
        mood, old_mood = (sim.get('mood') or {}).get('name'), (old.get('mood') or {}).get('name')
        if mood and mood != old_mood:
            events.append({'t': 'mood', 'who': sim['name'], 'mood': mood})
        if bool(sim.get('pregnant')) != bool(old.get('pregnant')):
            events.append({'t': 'pregnant', 'who': sim['name'], 'on': bool(sim.get('pregnant'))})
        if sim.get('dead') and not old.get('dead'):
            events.append({'t': 'death', 'who': sim['name']})
        if bool(sim.get('here')) != bool(old.get('here')):
            events.append({'t': 'here', 'who': sim['name'], 'on': bool(sim.get('here'))})
    return events


def _stable_key(snap):
    slim = dict(snap)
    sims = []
    for sim in slim.get('sims') or []:       # 「还剩多久」每分钟都在变，不算「变了」
        if sim.get('buffs'):
            sim = dict(sim)
            sim['buffs'] = [dict((k, v) for k, v in b.items() if k != 'left') if isinstance(b, dict) else b
                            for b in sim['buffs']]
        sims.append(sim)
    slim['sims'] = sims
    clock = dict(slim.get('clock') or {})
    clock.pop('minute', None)
    slim['clock'] = clock
    return json.dumps(slim, sort_keys=True, ensure_ascii=False)


def _look(now):
    snap = game.snapshot(his_names(), her_names())
    stamp = game.now_ms()
    for event in _diff_events(_state['prev'], snap):
        event['at'] = stamp
        link.push_event(event)
    key = _stable_key(snap)
    if _state['force'] or key != _state['last_key'] or now - _state['last_sent'] >= RESEND_EVERY:
        link.push_state(snap)
        _state['last_key'] = key
        _state['last_sent'] = now
        _state['force'] = False
    _state['prev'] = snap


def on_tick():
    if link is None or _state['busy']:
        return
    _state['busy'] = True
    try:
        screen = game.screen()
        running = screen in ('live', 'build')
        link.active = screen != 'away'
        if screen != _state['screen']:
            _state['screen'] = screen
            link.screen = screen
            link.push_event({'t': 'screen', 'screen': screen, 'at': game.now_ms()})
            _state['force'] = True
        if running != _state['was_running']:
            _state['was_running'] = running
            _state['prev'] = None
            _state['force'] = True
        while _later:
            job = _later.pop(0)
            try:
                job()
            except Exception:
                log.once('later', '后台结果弹不出来：%s' % log.tail_error())
        for _ in range(MAX_CMDS_PER_TICK):
            try:
                cmd = link.inbox.get_nowait()
            except Exception:
                break
            _run_command(cmd)
        if running:
            now = time.time()
            if not his_names() and not _state.get('nagged') and screen == 'live':
                _state['nagged'] = True
                try:
                    game.notify('Sul Sul', '还没告诉我哪个小人是 TA。按 %s 打开左上角的输入条，输入 ta who，' % game.CONSOLE_KEYS +
                                            '照它列出来的编号选一下。只用设一次。')
                except Exception:
                    log.once('nag', '提醒弹不出来：%s' % log.tail_error())
            if now - _state['last_snap'] >= SNAP_EVERY:
                _state['last_snap'] = now
                try:
                    _look(now)
                except Exception:
                    log.once('look', '读状态出错：%s' % log.tail_error())
                job = names.flush(link)     # 这一眼里碰到的新名字，交给后台去查
                if job is not None:
                    _background(job)
    finally:
        _state['busy'] = False


def install():
    global link, cfg
    cfg = log.load_config()
    link = Link(cfg.get('port') or 47931)
    link.start()
    _background(_key_loop)
    try:
        game.install_cas_watch()
    except Exception:
        log.once('caswatch', '认不出捏人界面（只影响「她在捏人」这句提示）：%s' % log.tail_error())
    import game_services
    original = game_services.on_tick
    if getattr(original, '_sulsul', False):
        return

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            on_tick()
        except Exception:
            log.once('tick', '泵出错：%s' % log.tail_error())
        return result

    wrapped._sulsul = True
    game_services.on_tick = wrapped
    log.info('泵装好了，转发程序端口 %s，TA 的小人：%s' % (link.port, '/'.join(his_names()) or '还没设'))
