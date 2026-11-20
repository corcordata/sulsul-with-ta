"""她在输入框里打字点确定：字要收到，而且要告诉游戏「收下了」，不然控制台会印一行像报错的字（Python 3.7）。"""
import os
import sys

ts4script = sys.argv[1]
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import sulsul  # noqa: E402,F401
from sulsul import game  # noqa: E402
import world  # noqa: E402

got = []
game.ask('跟 TA 说', '想跟 TA 说什么？', got.append)
dialog = world.DIALOGS[-1]
dialog.answer('看得见吗')
assert got == ['看得见吗'], got
assert dialog.input_ok is True, '游戏会把 False 当成没收下，在控制台印报错'

# 点了取消：不回调
got2 = []
game.ask('跟 TA 说', '想跟 TA 说什么？', got2.append)
cancelled = world.DIALOGS[-1]
cancelled.on_text_input('text_input', '不发了')
cancelled.accepted = False
for fn in cancelled._listeners:
    fn(cancelled)
assert got2 == []
print('OK', sulsul.VERSION)
