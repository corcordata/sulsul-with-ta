"""假游戏主循环（Python 3.7）：从打好的 .ts4script 里载入 mod，照时间表演一遍玩家会做的事。
外面的 e2e.py 同时假装是 AI。跑完把游戏这头看到的东西印成 JSON。"""
import json
import os
import sys
import time

ts4script, seconds = sys.argv[1], float(sys.argv[2])
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import game_services  # noqa: E402
import services  # noqa: E402
import world  # noqa: E402
import simslink  # noqa: E402,F401
from sims4 import commands  # noqa: E402


def ta(*words):
    return lambda: commands.REGISTERED['ta'](*words, _connection=1)


plan = [
    (1.0, ta('status')),                    # 还没设小人：status 里要写「还没设」
    (2.0, ta('ta', '不存在')),               # 家里没有这个名字：不记，把家里有谁告诉玩家
    (2.1, ta('who')),
    (2.2, ta('ta', '1')),                    # 按编号选：控制台里常常打不了中文
    (2.3, ta('me', '9')),                    # 没有这个号
    (2.4, ta('me', '小椴')),
    (2.6, ta('status')),
    (4.0, ta('你在干嘛')),
    (7.0, lambda: world.HER._sim.si_state.append(world.Interaction('bed_Sleep', world.BED))),
    (20.0, ta('pic')),
    (26.0, lambda: world.HER._sim.si_state.append(
        world.Interaction('mixer_social_Kiss_targeted_romance', world.STRANGER._sim))),
]
start = time.time()
while time.time() - start < seconds:
    game_services.on_tick()
    time.sleep(0.05)
    while plan and time.time() - start >= plan[0][0]:
        plan.pop(0)[1]()
    for dialog in list(world.DIALOGS):
        if not getattr(dialog, 'done', False):
            dialog.done = True
            dialog.answer('我在做饭呀')

print(json.dumps({'notifications': world.NOTIFICATIONS, 'executed': world.EXECUTED,
                  'console': commands.CheatOutput.lines, 'dialogs': [(d.title, d.text) for d in world.DIALOGS],
                  'his_outfit': world.HIM._outfit, 'funds': services._Funds.money,
                  'his_queue': [i.affordance.__name__ + (' (cancelled)' if i.cancelled else '') for i in world.HIM._sim.queue]},
                 ensure_ascii=False))
