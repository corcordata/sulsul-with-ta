"""0.1.2：她在哪个界面。用假游戏把 live → 捏人 → 读盘 → live → 建造 → 主菜单 走一遍（Python 3.7）。"""
import os
import sys

ts4script = sys.argv[1]
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import game_services  # noqa: E402
import services  # noqa: E402
import simslink  # noqa: E402,F401
from simslink import game, pump  # noqa: E402
from sims4 import commands  # noqa: E402

link = pump.link


def tick():
    game_services.on_tick()
    return link.screen


def events():
    with link._lock:
        out = [e.get('screen') for e in link._events if e.get('t') == 'screen']
        link._events = []
    return out


assert getattr(commands.client_cheat, '_simslink', False), '捏人监听没装上'
assert tick() == 'live' and events() == ['live']
assert tick() == 'live' and events() == []            # 没变就不重复报

# 她点了「在 CAS 里修改」：游戏给客户端发 exit2cas，然后存档停掉
commands.client_cheat('sims.exit2cas 1 2 3', 1)
assert commands.CLIENT_CHEATS[-1] == 'sims.exit2cas 1 2 3'   # 原来的指令照常发出去
for _ in range(5):                                    # 指令发出后存档还会再跑几拍，这几拍还算在游戏里
    assert tick() == 'live'
assert events() == []
services.ZONE.is_zone_running = False
assert tick() == 'cas' and events() == ['cas']
services.ZONE = None                                  # 捏人时存档整个卸掉也一样
assert tick() == 'cas' and events() == []

# 捏人时他让小人做事：直接告诉他原因；说话不拦
link._results = []
link.inbox.put({'id': 1, 'op': 'do', 'args': {'target': '小椴', 'name': 'kiss'}})
tick()
assert link._results[-1]['ok'] is False and '捏人界面' in link._results[-1]['text'], link._results

# 捏完回来：先读盘（还算捏人那一段），跑起来之后回到 live
services.ZONE = services._Zone()
services.ZONE.is_zone_running = False
assert tick() == 'cas'
services.ZONE.is_zone_running = True
assert tick() == 'live' and events() == ['live']
assert game._cas['pending_at'] == 0.0

# 点了去捏人又取消：三分钟都没停，标记作废，之后读盘不会被认成捏人
commands.client_cheat('sims.exit2caswithhouseholdid 1 2', 1)
assert tick() == 'live'
game._cas['pending_at'] -= game.CAS_GIVE_UP + 1
assert tick() == 'live' and game._cas['pending_at'] == 0.0
assert events() == []

# 建造模式
services.ZONE.is_in_build_buy = True
assert tick() == 'build' and events() == ['build']
services.ZONE.is_in_build_buy = False
assert tick() == 'live' and events() == ['live']

# 没经过捏人就停了：读盘；存档没了：主菜单 / 地图
services.ZONE.is_zone_running = False
assert tick() == 'loading' and events() == ['loading']
services.ZONE = None
assert tick() == 'away' and events() == ['away']
assert link.active is False                           # 不在存档里就慢点敲门

body = link._take()
assert body['screen'] == 'away', body
print('OK', simslink.VERSION)
