"""动作、状态在游戏里的名字（她屏幕上看到的那个，中文版就是中文）。

游戏脚本里每个名字只是一个号码，字在游戏的字库文件里，这里读不到；
所以把号码交给本机的小转发程序去查，查回来的记在手上。
规矩：游戏线程只看手上有的（label），没有的记一笔，由后台线程去问（fetch / flush）。
"""
import re
import threading
import time

_cache = {}          # 号码 → 字；'' = 查过了，没有
_pending = set()     # 游戏线程碰到过、还没去问的
_lock = threading.Lock()
_flags = {'busy': False, 'dead_until': 0.0}

_TOKEN_F = re.compile(r'\{F\d+\.[^{}]*\}')            # {F0.她}：女版，去掉
_TOKEN_M = re.compile(r'\{M\d+\.([^{}]*)\}')          # {M0.他}：男版，留里面的字
_TOKEN_TARGET = re.compile(r'\{1\.Sim[^{}]*\}')       # {1.SimFirstName}：对方
_TOKEN_ACTOR = re.compile(r'\{0\.Sim[^{}]*\}')        # {0.SimFirstName}：这个小人自己
_TOKEN_ANY = re.compile(r'\{[^{}]*\}')
_TAG = re.compile(r'<[^<>]{1,80}>')                   # <b>、<font color='#510061'>：有些 mod 的名字带着颜色


def key_of(thing, attr='display_name'):
    """动作 / 状态的名字号码。读不到就 0。"""
    try:
        name = getattr(thing, attr, None)
        if name is None:
            return 0
        if isinstance(name, int):
            return name & 0xFFFFFFFF
        string_id = getattr(name, '_string_id', None)
        if isinstance(string_id, int):
            return string_id & 0xFFFFFFFF
        made = name() if callable(name) else name
        return int(getattr(made, 'hash', 0) or 0) & 0xFFFFFFFF
    except Exception:
        return 0


def clean(text):
    """字库里的名字带着占位（{0.SimFirstName}、{M0.他}{F0.她}）：收拾成能读的。"""
    text = _TAG.sub('', str(text))
    text = _TOKEN_F.sub('', text)
    text = _TOKEN_M.sub(r'\1', text)
    text = _TOKEN_TARGET.sub('对方', text)
    text = _TOKEN_ACTOR.sub('TA', text)
    text = _TOKEN_ANY.sub('', text)
    return ' '.join(text.split()).strip(' :：,，')


def label(key):
    """手上有就给；没有就给空的，并记一笔等后台去问。"""
    if not key:
        return ''
    with _lock:
        if key in _cache:
            return _cache[key]
        _pending.add(key)
    return ''


def missing(keys):
    with _lock:
        return [k for k in set(keys) if k and k not in _cache]


def fetch(link, keys, timeout=12):
    """后台线程用：把还不知道的号码拿去问小转发程序。问到了回 True。"""
    keys = missing(keys)[:2000]
    if not keys:
        return True
    if time.time() < _flags['dead_until']:
        return False
    reply = link.local('/local/names', {'keys': keys}, timeout=timeout)
    found = reply.get('names') if isinstance(reply, dict) else None
    if not isinstance(found, dict):
        _flags['dead_until'] = time.time() + 60     # 旧版转发程序不会查，或者没开：过一分钟再问
        return False
    complete = bool(reply.get('ready'))
    with _lock:
        for key in keys:
            text = found.get(str(key))
            if text is not None:
                _cache[key] = clean(text)
            elif complete:
                _cache[key] = ''                    # 字库都翻过了，确实没有
        _pending.difference_update(_cache)
    return True


def flush(link):
    """泵隔一阵叫一次：有攒着的就给一个后台要跑的活，没有就 None。"""
    with _lock:
        if _flags['busy'] or not _pending or time.time() < _flags['dead_until']:
            return None
        keys = list(_pending)
        _flags['busy'] = True

    def job():
        try:
            fetch(link, keys)
        finally:
            _flags['busy'] = False

    return job
