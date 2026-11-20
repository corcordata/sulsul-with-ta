"""0.1.1 的显示清理：真游戏里报上来的那几个丑名字，照原样喂进去看结果（Python 3.7）。"""
import os
import sys

ts4script = sys.argv[1]
sys.path[:0] = [ts4script, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakegame')]

import simslink  # noqa: E402,F401
from simslink import game  # noqa: E402
import world  # noqa: E402

buffs = ['kawaiistacie_SliceofLifeMenstrualCycle_3XQUKHFVZM2',
         'Kawaiistacie_PersonalityMod_BuffAutonomousPicker/3196500040',
         'kawaiistacie_SliceofLifeMenstrualCycle_EZAE8VAAFR2',
         'kawaiistacie_SliceofLifeMenstrualCycle_KQPW3AIL782',
         'buff_Environment_BBGameplayEffects_GoodEnvironmentSmall', 'Buff_FirstKiss']
assert game.clean_tags(buffs, 10) == ['kawaiistacie_SliceofLifeMenstrualCycle',
                                      'buff_Environment_BBGameplayEffects_GoodEnvironmentSmall',
                                      'Buff_FirstKiss'], game.clean_tags(buffs, 10)

bits = ['relationshipBit_Fear_BeingCheatedOn_Tracker', 'RomanticCombo_Lovebirds', 'friendship-friend',
        'TURBODRIVER:WickedWhims_Relbit_Nudity_ReactionCooldown', 'relbit_SocialContext_Casual',
        'romantic_FirstKiss']
assert game.clean_tags(bits, 10) == ['RomanticCombo_Lovebirds', 'friendship-friend', 'romantic_FirstKiss']
assert game.clean_tags(['a', 'b', 'c'], 2) == ['a', 'b']


class Part(object):
    is_sim = False

    def __init__(self, owner):
        self.part_owner = owner


Part.__name__ = 'Part(object_bathtub_EP05STONE)'
tub = world.Obj('object_bathtub_EP05STONE', world.Vec(0, 0, 0), [])
assert game.object_label(Part(tub)) == 'object_bathtub_EP05STONE'
orphan = Part(None)
assert game.object_label(orphan) == 'object_bathtub_EP05STONE', game.object_label(orphan)
assert game.object_label(world.FRIDGE) == 'object_Fridge_Modern'
assert game.describe_interaction(world.Interaction('bathtub_TakeBath', Part(tub))) == {
    'name': 'bathtub_TakeBath', 'target': 'object_bathtub_EP05STONE'}

snap = game.snapshot(['澈'])
him = [s for s in snap['sims'] if s.get('his')][0]
assert [b['t'] for b in him['buffs']] == ['Buff_FirstKiss'], him['buffs']
assert him['rel']['林小椴']['bits'] == ['romantic-Married'], him['rel']
print('OK', simslink.VERSION)
