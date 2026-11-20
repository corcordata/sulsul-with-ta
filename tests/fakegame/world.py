"""假游戏：只够把 mod 的流程跑一遍（Python 3.7）。真接口对不对，只有她电脑上的游戏说了算。"""
import itertools

NOTIFICATIONS = []
DIALOGS = []
EXECUTED = []
_ids = itertools.count(1000)


class Vec(object):
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Name(object):
    """游戏里的名字：只有一个号码，字在字库文件里。"""
    __slots__ = ('_string_id',)

    def __init__(self, string_id):
        self._string_id = string_id


def name_key(name):
    """假字库用的号码：名字的 crc32（真游戏里是 EA 自己的哈希，这里只要两头对得上）。"""
    import zlib
    return zlib.crc32(name.encode('utf-8')) & 0xFFFFFFFF


def cls(name):
    return type(name, (), {'display_name': _Name(name_key(name)), 'buff_name': _Name(name_key(name))})


class Result(object):
    def __init__(self, ok, reason=''):
        self.ok, self.reason = ok, reason

    def __bool__(self):
        return self.ok

    def __str__(self):
        return self.reason or ('ok' if self.ok else 'failed')


class Aop(object):
    def __init__(self, name, target, ok=True, subs=()):
        self.affordance = cls(name)
        self.affordance.allow_user_directed = True
        _subs = list(subs)
        self.affordance.potential_pie_menu_sub_interactions_gen = staticmethod(
            lambda target, context, handler, **kw: iter([(s, None) for s in _subs]))
        self.target = target
        self.interaction_parameters = {}
        self._ok = ok

    def test(self, context):
        return Result(self._ok, '' if self._ok else 'too tired')

    def test_and_execute(self, context):
        if not self._ok:
            return Result(False, 'too tired')
        EXECUTED.append((context.sim.sim_info.first_name, self.affordance.__name__, getattr(self.target, 'label', '?')))
        context.sim.queue.append(Interaction(self.affordance.__name__, self.target))
        return Result(True)


class Interaction(object):
    def __init__(self, name, target=None):
        self.affordance = cls(name)
        self.super_affordance = self.affordance
        self.target = target
        self.cancelled = False

    def cancel(self, finishing_type, cancel_reason_msg=''):
        self.cancelled = True


class Stat(object):
    def __init__(self, name, value, visible=True):
        self.stat_type = cls(name)
        self.is_visible = visible
        self._value = value

    def get_value(self):
        return self._value


class Tracker(object):
    def __init__(self, stats):
        self._stats = stats

    def get_all_commodities(self):
        return list(self._stats)


class Buff(object):
    def __init__(self, name, visible=True, mood=None, weight=0, reason=None, timeout=0):
        self.buff_type = cls(name)
        self.buff_type.buff_description = _Name(name_key(name + '/desc'))
        self.visible = visible
        self.mood_type = cls(mood) if mood else None
        self.mood_weight = weight
        self.buff_reason = type('LS', (), {'hash': name_key(reason)})() if reason else None
        self._timeout = timeout             # 「到几点结束」，单位：游戏分钟（假的钟现在是 1000）

    def get_timeout_time(self):
        return (self._timeout, 1.0)


class RelTracker(object):
    def __init__(self, scores):
        self.scores = scores

    def has_relationship(self, other_id):
        return other_id in self.scores

    def get_relationship_score(self, other_id, track=None):
        return self.scores[other_id][0 if track.__name__ == 'LTR_Friendship_Main' else 1]

    def get_all_bits(self, target_sim_id=None):
        return [cls('romantic-Married'), cls('ShortTermBits_Friendship_x')]


class Pregnancy(object):
    def __init__(self, on):
        self.is_pregnant = on


class Sim(object):
    is_sim = True

    def __init__(self, info, pos):
        self.sim_info = info
        self.position = pos
        self.routing_surface = None
        self.si_state = []
        self.queue = []
        self.id = info.sim_id
        self.label = info.first_name

    def potential_interactions(self, context):
        kiss = Aop('mixer_social_Kiss_targeted_romance', self)
        hug = Aop('mixer_social_Hug_targeted_friendly', self)
        return [Aop('sim_Chat', self, subs=[kiss, hug]), Aop('sim-stand', self), Aop('sim_WooHoo', self, ok=False)]

    def potential_phone_interactions(self, context):
        return [Aop('phone_JoinCareer', self)]


class SimInfo(object):
    def __init__(self, first, last, sim_id, pos, mood='Mood_Happy', here=True, pregnant=False):
        self.first_name, self.last_name, self.sim_id = first, last, sim_id
        self.commodity_tracker = Tracker([Stat('motive_Hunger', -62.3), Stat('motive_Energy', 41.0),
                                          Stat('commodity_Hidden', 3, visible=False)])
        self.Buffs = [Buff('Buff_FirstKiss', mood='Mood_Flirty', weight=2, reason='reason_Kiss', timeout=1200),
                      Buff('Buff_Hidden', visible=False)]
        self.relationship_tracker = RelTracker({})
        self.pregnancy_tracker = Pregnancy(pregnant)
        self._mood = cls(mood)
        self._sim = Sim(self, pos) if here else None
        self.is_dead = False
        # 衣柜：类别号 → 有几套。真游戏里每个小人至少有日常 / 睡衣 / 洗澡那套
        self.wardrobe = {0: 2, 1: 1, 3: 1, 5: 1}
        self._outfit = (0, 0)
        self.outfit_locked = False      # 测试用：假装游戏不让换

    def get_current_outfit(self):
        from sims.outfits.outfit_enums import OutfitCategory
        return (OutfitCategory(self._outfit[0]), self._outfit[1])

    def has_outfit(self, outfit):
        return int(outfit[1]) < self.wardrobe.get(int(outfit[0]), 0)

    def set_current_outfit(self, outfit):
        if not self.outfit_locked:
            self._outfit = (int(outfit[0]), int(outfit[1]))

    def try_set_current_outfit(self, outfit, do_spin=False, **kwargs):
        self.set_current_outfit(outfit)

    def get_sim_instance(self):
        return self._sim

    def get_mood(self):
        return self._mood

    def get_mood_intensity(self):
        return 2


class Obj(object):
    is_sim = False

    def __init__(self, name, pos, actions):
        self.id = next(_ids)
        self.position = pos
        self.routing_surface = None
        self.label = name
        self._actions = actions
        self.__class__ = type(name, (Obj,), {})

    def is_on_active_lot(self):
        return True

    def potential_interactions(self, context):
        return [Aop(a, self) for a in self._actions]


HIM = SimInfo('澈', '林', 1, Vec(0, 0, 0))
HER = SimInfo('小椴', '林', 2, Vec(1, 0, 1), mood='Mood_Flirty', pregnant=True)
KID = SimInfo('团子', '林', 3, Vec(0, 0, 0), here=False)
STRANGER = SimInfo('Bella', 'Goth', 9, Vec(30, 0, 30))
HIM.relationship_tracker = RelTracker({2: (80.4, 100.0)})
HER.relationship_tracker = RelTracker({1: (80.4, 100.0)})
HER._sim.si_state.append(Interaction('fridge_Cook', None))
FRIDGE = Obj('object_Fridge_Modern', Vec(3, 0, 0), ['fridge_Cook', 'fridge_QuickMeal'])
BED = Obj('object_Bed_Double', Vec(8, 0, 0), ['bed_Sleep', 'bed_Nap'])
BED2 = Obj('object_Bed_Double', Vec(2, 0, 0), ['bed_Sleep', 'bed_Nap'])
