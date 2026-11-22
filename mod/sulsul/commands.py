"""玩家在游戏里用的命令。按 F9（小转发程序管的快捷键）直接弹输入框；
或者 Ctrl+Shift+C 打开控制台，输入 ta 回车。

ta             弹一个输入框，打完点确定
ta 你在干嘛      直接发这一句（控制台里打不了中文时用上面那个）
ta status      看连没连上、哪个小人是 TA、哪个是我
ta who         把家里的小人编上号列出来
ta ta 1        1 号小人是 TA（也可以写名字的一部分；ta ai / ta xj 是同一个意思）
ta me 2        2 号小人是我
ta call mu     给这个指令再起一个叫法：之后 mu 你在干嘛、mu who 都行，ta 照样能用
ta key F9      换说话快捷键（F1 到 F11）；ta key 看现在是哪个
ta boss F10    换老板键（按一下：游戏缩下去 + 静音 + 暂停）
ta ime off     输入框弹出来时不替我切中文（想打英文的时候）；ta ime on 恢复自动切
ta pic         把刚截的那张图（按 C 截的）发给 TA；ta pic 3 发最新的三张
ta pics on     之后新截的图自动发给 TA；ta pics off 关掉
ta wake off    游戏里出了事不再自己去叫 TA（默认是开的）；ta wake on 打开
"""
import re
import time

import sims4.commands

from sulsul import game, log, pump


def _names():
    return 'TA 的小人：%s｜我的小人：%s' % ('/'.join(pump.his_names()) or '还没设（ta who）',
                                    '/'.join(pump.her_names()) or '还没设（ta who）')


def _status():
    link = pump.link
    if link is None:
        return 'Sul Sul 没启动，看 SulSul.log'
    if link.connected:
        return '连着呢（%d 秒前刚通过话）。%s' % (max(0, int(time.time() - link.last_ok)), _names())
    return '没连上小转发程序：%s —— 先把 SulSulBridge 打开。%s' % (link.last_error or '还没试过', _names())


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
    """ta ta 2 / ta me 小椴：编号或名字都行，记进 SulSul.cfg。对不上就不记，把家里有谁列给玩家。"""
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


_WORD = re.compile(r'^[a-z][a-z0-9]{1,11}$')
# 游戏自己的秘籍和常见 mod 已经占着的词，不能拿来当叫法
_TAKEN = ('help', 'sims', 'bb', 'cas', 'stats', 'traits', 'careers', 'money', 'motherlode', 'kaching', 'rosebud',
          'death', 'households', 'aspirations', 'fps', 'headlineeffects', 'hovereffects', 'testingcheats',
          'resetsim', 'freerealestate', 'fullscreen', 'quit', 'debug', 'mc', 'mccc', 'ww', 'call', 'who', 'me')
_extra = []


def _register(word):
    """再登记一个叫法，跟 ta 是同一个指令。登记不上（游戏不让在半路加）就等下次开游戏。"""
    if word in ('ta', 'sulsul') or word in _extra:
        return True
    try:
        sims4.commands.Command(word, command_type=sims4.commands.CommandType.Live)(_ta)
        _extra.append(word)
        return True
    except Exception:
        log.once('call', '叫法「%s」现在登记不上（下次开游戏再试）：%s' % (word, log.tail_error()))
        return False


def _call(word):
    """ta call mu：给指令再起一个叫法，记进 SulSul.cfg。ta call 看现在有哪些。"""
    saved = [str(w) for w in (pump.cfg.get('commands') or []) if w]
    if not word:
        return ['现在能用的叫法：%s。想加一个就输入 ta call 加上你想用的词，比如 ta call mu' % '、'.join(['ta'] + saved)]
    if not _WORD.match(word) or word in _TAKEN:
        return ['「%s」不行：要 2 到 12 个英文字母或数字、字母开头，而且不能是游戏自己的秘籍词。' % word]
    if word not in saved:
        saved = (saved + [word])[-5:]
        pump.cfg['commands'] = saved
        log.save_config({'commands': saved})
    if _register(word):
        return ['好了：以后 %s 跟 ta 一样用，比如 %s 你在干嘛、%s who。ta 照样能用。' % (word, word, word)]
    return ['记下了：下次开游戏起，%s 跟 ta 一样用。' % word]


@sims4.commands.Command('ta', 'sulsul', command_type=sims4.commands.CommandType.Live)
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
        if low == 'call' or low.startswith('call '):
            for line in _call(low[4:].strip()):
                output(line)
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
        output('出错了，看 SulSul.log')
        return False


for _word in [str(w) for w in (pump.cfg.get('commands') or []) if w]:     # 以前起过的叫法，开游戏时登记上
    if _WORD.match(_word) and _word not in _TAKEN:
        _register(_word)
