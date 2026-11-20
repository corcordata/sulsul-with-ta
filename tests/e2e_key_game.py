"""假游戏主循环（Python 3.7）：跑「按快捷键说话」这条路。要先开着小转发程序（带 SULSUL_FAKE_SHOT，
这样它认 /local/press，替她按那一下）。服务器不用开：这条路只在本机走。

  ① 3 秒时「她按了快捷键」→ 弹出「跟 TA 说」的输入框，转发程序收到「切中文」
  ② 框开着的时候她又按了一次 → 不叠第二个框
  ③ 她打完点确定 → 这句话进了要交给服务器的队列，转发程序收到「切英文」
  ④ 她在控制台打 ta key F10 → 右上角告诉她换好了
"""
import http.client
import json
import os
import sys
import time

ts4script, seconds = sys.argv[1], float(sys.argv[2])
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import game_services  # noqa: E402
import world  # noqa: E402
import sulsul  # noqa: E402,F401
from sulsul import pump  # noqa: E402
from sims4 import commands  # noqa: E402


def press(which='talk'):
    body = ('{"which": "%s"}' % which).encode()
    conn = http.client.HTTPConnection('127.0.0.1', 47931, timeout=5)
    conn.request('POST', '/local/press', body=body, headers={'Content-Type': 'application/json', 'Content-Length': str(len(body))})
    conn.getresponse().read()
    conn.close()


said = []
real_say = pump.her_say
pump.her_say = lambda text: (said.append(text), real_say(text))[1]
plan = [
    (3, press),
    (5, press),
    (7, lambda: world.DIALOGS[-1].answer('我在这呢')),
    (8, lambda: commands.REGISTERED['ta']('key', 'f8', _connection=1)),
    (9, lambda: commands.REGISTERED['ta']('boss', 'f8', _connection=1)),      # 跟说话键撞了：不让换
    (10, lambda: press('boss')),                                               # ⑤ 老板键：mod 把游戏暂停
]
start = time.time()
while time.time() - start < seconds:
    game_services.on_tick()
    time.sleep(0.05)
    while plan and time.time() - start >= plan[0][0]:
        plan.pop(0)[1]()

titles = [d.title for d in world.DIALOGS]
assert titles == ['跟 TA 说'], '该只弹一个框：%r' % titles
assert said == ['我在这呢'], said
assert pump._state['asking'] == 0.0
assert any('按 F8 跟 TA 说话' in n[1] for n in world.NOTIFICATIONS), world.NOTIFICATIONS
assert any('两个不能用同一个键' in n[1] for n in world.NOTIFICATIONS), world.NOTIFICATIONS
import services  # noqa: E402
assert services._Clock.set_to is not None, '老板键该把游戏暂停'
assert titles == ['跟 TA 说'], '老板键不该弹输入框'
paused = str(services._Clock.set_to)
print(json.dumps({'dialogs': titles, 'said': said, 'paused': paused, 'notifications': world.NOTIFICATIONS,
                  'console': commands.CheatOutput.lines}, ensure_ascii=False, indent=1))
print('OK', sulsul.VERSION)
