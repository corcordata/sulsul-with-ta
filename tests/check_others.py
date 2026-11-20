"""0.2.2：家里人以外的小人拆成「这块地上的」和「街上路过的」（Python 3.7，跑打好的 ts4script）。
起因：他把整条街载入的路人读成了「窗外有八个人在看」。"""
import os
import sys

ts4script = sys.argv[1]
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import sulsul  # noqa: E402,F401
from sulsul import game  # noqa: E402
import services  # noqa: E402
import world  # noqa: E402

GUEST = world.SimInfo('莫拉', '菲尔斯', 10, world.Vec(2, 0, 1))       # 进了屋，就在她旁边
WALKERS = [world.SimInfo('路人%d' % n, '', 20 + n, world.Vec(40 + n, 0, 40)) for n in range(8)]
EVERYONE = [world.HIM, world.HER, world.KID, world.STRANGER, GUEST] + WALKERS
services.sim_info_manager = lambda: services._Mgr(EVERYONE)


class Lot(object):
    asked = 0

    def is_position_on_lot(self, position, tolerance=0):
        Lot.asked += 1
        return abs(position.x) <= 20 and abs(position.z) <= 20


def names(snap):
    return snap['others'], snap['street']


# ① 正路：问这块地
services.ZONE.lot = Lot()
snap = game.snapshot(('林澈',))
assert snap['others'] == [game.sim_name(GUEST)], snap['others']
assert snap['street']['n'] == 9, snap['street']                      # Bella + 8 个路人
assert len(snap['street']['names']) == 6 and game.sim_name(world.STRANGER) in snap['street']['names']
assert Lot.asked == 10
her = [s for s in snap['sims'] if s.get('active')][0]
assert game.sim_name(GUEST) in her['near'] and game.sim_name(world.HIM) in her['near'], her
assert not any(n.startswith('路人') for s in snap['sims'] for n in s.get('near', []))

# ② 这块地问不了：改问小人自己
del services.ZONE.lot
world.Sim.is_on_active_lot = lambda self, tolerance=0: abs(self.position.x) <= 20
snap = game.snapshot(('林澈',))
assert snap['others'] == [game.sim_name(GUEST)] and snap['street']['n'] == 9, names(snap)

# ③ 两样都问不了：离家里人 12 米以内才算
del world.Sim.is_on_active_lot
snap = game.snapshot(('林澈',))
assert snap['others'] == [game.sim_name(GUEST)] and snap['street']['n'] == 9, names(snap)

# ④ 一个外人都没有：两样都是空的，但 street 这把钥匙一定在（服务器靠它认新版）
services.sim_info_manager = lambda: services._Mgr([world.HIM, world.HER, world.KID])
snap = game.snapshot(('林澈',))
assert snap['others'] == [] and snap['street'] == {'n': 0, 'names': []}, names(snap)

print('OK', sulsul.VERSION)
