"""日志和配置都放在 mod 自己的文件夹里（.ts4script 旁边）。"""
import json
import os
import time
import traceback

_MAX_BYTES = 1024 * 1024

DEFAULTS = {
    'port': 47931,
    # 名字里带这些字的小人是 AI 的那个。游戏控制台 ta ai 名字 会写到 SimsLink.cfg 里
    'ai_names': [],
    # 名字里带这些字的小人是玩家自己（TA 被别人亲了、快饿晕了，游戏会去叫 AI）。ta me 名字
    'player_names': [],
}


def mod_dir():
    here = os.path.abspath(__file__)
    probe = here
    for _ in range(8):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        if probe.lower().endswith('.ts4script'):
            return parent
        probe = parent
    # 没打包（Scripts 文件夹直接放 .py）时：.../Mods/SimsLink/Scripts/simslink/log.py
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def sims_dir():
    """…\\The Sims 4 那一层（Mods 的上一层）：截图文件夹 Screenshots 就在它里面。"""
    return os.path.dirname(os.path.dirname(_dir()))


_DIR = None


def _dir():
    global _DIR
    if _DIR is None:
        try:
            _DIR = mod_dir()
        except Exception:
            _DIR = os.path.expanduser('~')
    return _DIR


def _path():
    return os.path.join(_dir(), 'SimsLink.log')


def _write(level, msg):
    try:
        path = _path()
        try:
            if os.path.getsize(path) > _MAX_BYTES:
                os.remove(path)
        except OSError:
            pass
        with open(path, 'a', encoding='utf-8') as f:
            f.write('%s [%s] %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), level, msg))
    except Exception:
        pass


def info(msg):
    _write('INFO', msg)


def warn(msg):
    _write('WARN', msg)


def exception(msg):
    _write('ERROR', '%s\n%s' % (msg, traceback.format_exc()))


_once = set()


def once(key, msg):
    """同一类毛病只记一次，免得每秒刷一行。"""
    if key in _once:
        return
    _once.add(key)
    _write('WARN', msg)


def tail_error():
    """给 AI 看的简短错误（最后一行）。"""
    text = traceback.format_exc().strip().splitlines()
    return text[-1] if text else 'unknown error'


def save_config(changes):
    """把几项设置记进 SimsLink.cfg（别的项原样留着），下次开游戏还在。"""
    path = os.path.join(_dir(), 'SimsLink.cfg')
    data = {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        pass
    data.update(changes)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        exception('SimsLink.cfg 写不进去')


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(_dir(), 'SimsLink.cfg'), 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        exception('SimsLink.cfg 读不了，先用默认值')
    return cfg
