"""Sul Sul：把 Sims 4 里发生的事写成字交给你家的 AI，把 TA 的话和动作带回游戏。

游戏里的 Python 是 3.7，没有 ssl，所以这里只跟本机的小转发程序（SulSulBridge）说话，
由它去连你自己的服务器。这个文件只管启动：任何一步出错都只写日志，不让游戏崩。
"""

VERSION = '1.0.0'

try:
    from sulsul import log
    log.info('Sul Sul %s 载入中' % VERSION)
    from sulsul import pump
    pump.install()
    from sulsul import commands  # noqa: F401  注册控制台命令
    log.info('Sul Sul 已就绪')
except Exception:  # pragma: no cover - 游戏里才会走到
    try:
        from sulsul import log as _log
        _log.exception('Sul Sul 启动失败')
    except Exception:
        pass
