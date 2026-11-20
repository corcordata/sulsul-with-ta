"""0.4.3：情绪状态照她点开看到的那张卡来读；WW 的数值不当需求；ta ime off/on（Python 3.7）。"""
import json
import os
import sys

ts4script = sys.argv[1]
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import simslink  # noqa: E402,F401
from simslink import game, log, names, pump  # noqa: E402
import world  # noqa: E402
from sims4 import commands  # noqa: E402

him = world.HIM
him.Buffs.append(world.Buff('buff_Sim_IsSleeping'))                       # 游戏里查不到名字的：先照内部名报
him.Buffs.append(world.Buff('Buff_Storm', mood='Mood_Scared', weight=1))  # 没期限、没来处
him.commodity_tracker._stats.append(world.Stat('TURBODRIVER:WickedWhims_Sex_Motive_Satisfaction', -100))
him.commodity_tracker._stats.append(world.Stat('motive_Vampire_Thirst', -40))

# 名字还没查到：先用内部名，情绪 / 加几 / 还剩多久照样有
rows = game._buffs(him)
assert rows == [{'t': 'Buff_FirstKiss', 'mood': 'Flirty', 'w': 2, 'left': 200}, {'t': 'buff_Sim_IsSleeping'},
                {'t': 'Buff_Storm', 'mood': 'Scared', 'w': 1}], rows
motives = game._motives(him)
assert 'Vampire_Thirst' in motives and not any(':' in k for k in motives), motives

# 查到了（假装小转发程序回了话）
key = world.name_key
names._cache.update({key('Buff_FirstKiss'): '初吻', key('Buff_FirstKiss/desc'): '嘴唇上还留着{1.SimFirstName}的味道。',
                     key('reason_Kiss'): '第一次接吻', key('Buff_Storm'): '暴风雨', key('Buff_Storm/desc'): '',
                     key('buff_Sim_IsSleeping'): '', key('buff_Sim_IsSleeping/desc'): ''})
rows = game._buffs(him)
assert rows[0] == {'t': '初吻', 'mood': 'Flirty', 'w': 2, 'from': '第一次接吻', 'left': 200}, rows[0]
cards = game.show_buff_cards(game.buff_cards(him))
assert cards[:2] == ['【初吻】调情 +2｜来自 第一次接吻｜还剩 3 小时 20 分', '  嘴唇上还留着{1.SimFirstName}的味道。'], cards
assert '【暴风雨】害怕 +1' in cards

# 「还剩多久」不算变了
snap = game.snapshot(('林澈',), ('小椴',))
k1 = pump._stable_key(snap)
him.Buffs[0]._timeout = 1150
k2 = pump._stable_key(game.snapshot(('林澈',), ('小椴',)))
assert k1 == k2

# ta ime off / on：记进 SimsLink.cfg，别的项留着
cfg_path = os.path.join(log._dir(), 'SimsLink.cfg')
with open(cfg_path, 'w', encoding='utf-8') as f:
    json.dump({'ai_names': ['林澈']}, f, ensure_ascii=False)
pump.cfg = log.load_config()
commands.REGISTERED['ta']('ime', 'off', _connection=1)
assert pump.cfg['auto_ime'] is False
saved = json.load(open(cfg_path, encoding='utf-8'))
assert saved == {'ai_names': ['林澈'], 'auto_ime': False}, saved
commands.REGISTERED['ta']('ime', 'on', _connection=1)
assert json.load(open(cfg_path, encoding='utf-8'))['auto_ime'] is True
os.remove(cfg_path)
print('OK', simslink.VERSION)
