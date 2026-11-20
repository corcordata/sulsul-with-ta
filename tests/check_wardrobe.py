"""0.4：他能换衣服、能给她打钱；状态里多了穿着什么、家里的存款、着火、谁是她（Python 3.7）。"""
import os
import sys

ts4script = sys.argv[1]
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import simslink  # noqa: E402,F401
from simslink import game, pump  # noqa: E402
import services  # noqa: E402
import world  # noqa: E402

pump.cfg = {'ai_names': ['林澈', '澈'], 'player_names': ['小椴']}
pump.link = type('L', (), {'push_event': lambda self, e: None})()
him = world.HIM


def fails(fn, *args):
    try:
        fn(*args)
    except game.OpError as exc:
        return str(exc)
    raise AssertionError('该报错的没报错')


# ── 换衣服 ──
assert game.current_outfit(him) == '日常 1'
assert game.list_outfits(him) == ['日常（2 套）', '正装', '睡衣', '不穿'], game.list_outfits(him)
assert pump._op_outfit({}) == '林澈 现在穿着 日常 1。能换的：日常（2 套）、正装、睡衣、不穿。', pump._op_outfit({})
assert pump._op_outfit({'name': '睡衣'}) == '换好了：睡衣 1。' and game.current_outfit(him) == '睡衣 1'
assert pump._op_outfit({'name': 'sleepwear'}) == '你本来就穿着 睡衣 1。'
assert pump._op_outfit({'name': '日常 2'}) == '换好了：日常 2。' and him._outfit == (0, 1)
assert pump._op_outfit({'name': 'formal'}) == '换好了：正装 1。'
assert pump._op_outfit({'name': '脱光'}) == '换好了：不穿 1。' and him._outfit == (5, 0)
assert '只有 2 套' in fails(pump._op_outfit, {'name': '日常 3'})
assert '你没有「泳装」' in fails(pump._op_outfit, {'name': '泳装'})
assert '没有「盔甲」这类衣服' in fails(pump._op_outfit, {'name': '盔甲'})
him.outfit_locked = True
assert '没换成，还穿着 不穿 1' in fails(pump._op_outfit, {'name': '日常'})
him.outfit_locked = False
pump._op_outfit({'name': '日常'})

# ── 打钱 ──
before = services._Funds.money
text = pump._op_money({'amount': '2000', 'text': '去买那个沙发'})
assert services._Funds.money == before + 2000
assert text == '转过去了 §2,000，她屏幕右上角看得到。家里现在有 §14,345。', text
assert world.NOTIFICATIONS[-1][:2] == ('林澈', '给你转了 §2,000：去买那个沙发'), world.NOTIFICATIONS[-1]
for bad in ('0', '-5', '999999', 'abc', None):
    assert '1 到 50000' in fails(pump._op_money, {'amount': bad})
assert services._Funds.money == before + 2000

# ── 状态 ──
snap = game.snapshot(pump.his_names(), pump.her_names())
by = dict((s['name'], s) for s in snap['sims'])
assert by['林澈'].get('his') and not by['林澈'].get('hers')
assert by['林小椴'].get('hers') and not by['林小椴'].get('his')
assert by['林澈']['outfit'] == '日常 1' and 'outfit' not in by['林团子']      # 不在场的不报穿着
assert snap['funds'] == before + 2000 and 'fire' not in snap

# ── 着火、去世：变成事件 ──
services.FIRE.fire_is_active = True
world.HER.is_dead = True
after = game.snapshot(pump.his_names(), pump.her_names())
events = pump._diff_events(snap, after)
assert {'t': 'fire', 'on': True} in events and {'t': 'death', 'who': '林小椴'} in events, events
services.FIRE.fire_is_active = False
world.HER.is_dead = False
assert {'t': 'fire', 'on': False} in pump._diff_events(after, game.snapshot(pump.his_names(), pump.her_names()))
print('OK', simslink.VERSION)
