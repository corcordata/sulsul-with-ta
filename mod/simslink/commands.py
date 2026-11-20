"""玩家在游戏里用的命令。按 F9（小转发程序管的快捷键）直接弹输入框；
或者 Ctrl+Shift+C 打开控制台，输入 ta 回车。

ta             弹一个输入框，打完点确定
ta 你在干嘛      直接发这一句（控制台里打不了中文时用上面那个）
ta status      看连没连上、哪个小人是 TA、哪个是我
ta who         把家里的小人编上号列出来
ta ta 1        1 号小人是 TA（也可以写名字的一部分；ta ai / ta xj 是同一个意思）
ta me 2        2 号小人是我
ta key F9      换说话快捷键（F1 到 F11）；ta key 看现在是哪个
ta boss F10    换老板键（按一下：游戏缩下去 + 静音 + 暂停）
ta ime off     输入框弹出来时不替我切中文（想打英文的时候）；ta ime on 恢复自动切
ta pic         把刚截的那张图（按 C 截的）发给 TA；ta pic 3 发最新的三张
ta pics on     之后新截的图自动发给 TA；ta pics off 关掉
ta wake off    游戏里出了事不再自己去叫 TA（默认是开的）；ta wake on 打开
"""
import time

import sims4.commands

from simslink import game, log, pump


def _names():
    return 'TA 的小人：%s｜我的小人：%s' % ('/'.join(pump.his_names()) or '还没设（ta who）',
                                    '/'.join(pump.her_names()) or '还没设（ta who）')


def _status():
    link = pump.link
    if link is None:
        return 'SimsLink 没启动，看 SimsLink.log'
    if link.connected:
        return '连着呢（%d 秒前刚通过话）。%s' % (max(0, int(time.time() - link.last_ok)), _names())
    return '没连上小转发程序：%s —— 先把 SimsLinkBridge 打开。%s' % (link.last_error or '还没试过', _names())


def _family():
    try:
        return [game.sim_name(info) for info in game.household_infos()]
    except Exception:
        return []


def _who():
    """ta who：家里的小人编上号列出来。控制台里常常打不了中文，所以选小人用编号。"""
    family = _family()
    if not family:
        return ['要先进到存档里，才看得到家里有谁。']
    return ['家里有：' + '　'.join('%d %s' % (n + 1, name) for n, name in enumerate(family)),
            'TA 是几号就输入 ta ta 编号，你自己是几号就输入 ta me 编号。比如：ta ta 1',
            '现在 ' + _names()]


def _set_name(which, arg):
    """ta ta 2 / ta me 小椴：编号或名字都行，记进 SimsLink.cfg。对不上就不记，把家里有谁列给玩家。"""
    label = 'TA 的小人' if which == 'ta_names' else '你的小人'
    if not arg:
        return _who()
    family = _family()
    if arg.isdigit():
        if not family:
            return ['要先进到存档里，才能按编号选。']
        if not 1 <= int(arg) <= len(family):
            return ['没有 %s 号。' % arg] + _who()[:1]
        name = family[int(arg) - 1]
    else:
        name = arg
        if family and not any(name.lower() in full.lower() for full in family):
            return ['家里没有名字带「%s」的小人。' % name] + _who()[:2]
    pump.set_names(which, [name])
    return ['记下了：%s是「%s」。' % (label, name)]


@sims4.commands.Command('ta', 'simslink', command_type=sims4.commands.CommandType.Live)
def _ta(*args, _connection=None):
    try:
        output = sims4.commands.CheatOutput(_connection)
    except Exception:
        output = lambda *_: None  # noqa: E731
    try:
        text = ' '.join(str(a) for a in args).strip()
        low = text.lower()
        if low in ('status', '状态'):
            output(_status())
            return True
        if low in ('who', '谁'):
            for line in _who():
                output(line)
            return True
        head = low.split(' ', 1)[0]
        if head in ('ta', 'ai', 'xj'):
            for line in _set_name('ta_names', text[len(head):].strip()):
                output(line)
            return True
        if head == 'me':
            for line in _set_name('player_names', text[2:].strip()):
                output(line)
            return True
        if low == 'pic' or (low.startswith('pic ') and low[4:].strip().isdigit()):
            count = int(low[4:].strip()) if low.startswith('pic ') else 1
            pump.her_pictures(max(1, min(6, count)))
            output('在发了，发完右上角会告诉你。')
            return True
        if low == 'boss' or low.startswith('boss '):
            pump.her_key(text[4:].strip(), 'boss')
            output('在问了，右上角会告诉你。')
            return True
        if low == 'key' or low.startswith('key '):
            pump.her_key(text[3:].strip())
            output('在问了，右上角会告诉你。')
            return True
        if low in ('ime on', 'ime off'):
            on = low.endswith('on')
            pump.her_ime(on)
            output('开了：输入框一弹出来自动切中文，关掉切回英文。' if on else '关了：输入法我不碰，你自己用 Shift 切。')
            return True
        if low in ('wake on', 'wake off'):
            on = low.endswith('on')
            pump.her_wake(on)
            output('开了：游戏里出了事会去叫 TA。' if on else '关了：你不叫 TA，TA 就不会自己冒出来。')
            return True
        if low in ('pics on', 'pics off'):
            pump.her_auto_share(low.endswith('on'))
            return True
        if text:
            pump.her_say(text)
            output('发给 TA 了。' if pump.link is not None and pump.link.connected else _status())
            return True

        pump.ask_her('跟 TA 说', '想跟 TA 说什么？')
        return True
    except Exception:
        log.exception('ta 命令出错')
        output('出错了，看 SimsLink.log')
        return False
