import world


class _Funds(object):
    money = 12345
    log = []

    def add(self, amount, reason, sim=None, **kwargs):
        _Funds.money += amount
        _Funds.log.append((amount, reason))


class _Fire(object):
    fire_is_active = False


FIRE = _Fire()


class _Household(object):
    home_zone_id = 77
    funds = _Funds()

    def sim_info_gen(self):
        return iter([world.HIM, world.HER, world.KID])


class _Zone(object):
    id = 77
    is_zone_running = True
    is_in_build_buy = False


ZONE = _Zone()   # 测试里改它：设成 None = 没有存档；is_zone_running=False = 停了


class _Client(object):
    active_sim_info = world.HER

    def create_interaction_context(self, sim, **kwargs):
        ctx = type('Ctx', (), {})()
        ctx.sim = sim
        ctx.pick = kwargs.get('pick')
        return ctx


class _Mgr(object):
    def __init__(self, items):
        self._items = items

    def get_all(self):
        return list(self._items)

    def values(self):
        return list(self._items)

    def get(self, key):
        for item in self._items:
            if getattr(item, 'id', None) == key:
                return item
        return None

    def get_first_client(self):
        return _Client()


class _Proto(object):
    name = '柳溪小屋'


class _Persist(object):
    def get_zone_proto_buff(self, zone_id):
        return _Proto()


class _Venue(object):
    def get_venue_tuning(self, zone_id):
        return type('venue_residential', (), {})


class _Now(object):
    def absolute_ticks(self):
        return 1000

    def day(self):
        return 3

    def hour(self):
        return 14

    def minute(self):
        return 5


class _Time(object):
    sim_now = _Now()


class _Clock(object):
    clock_speed = type('S', (), {'name': 'NORMAL'})()
    set_to = None

    def set_clock_speed(self, mode):
        _Clock.set_to = mode


class _Tracks(object):
    def get(self, track_id):
        return type('LTR_Friendship_Main' if track_id == 16650 else 'LTR_Romance_Main', (), {})


def active_household(): return _Household()
def current_zone(): return ZONE
def client_manager(): return _Mgr([])
def active_sim_info(): return world.HER
def sim_info_manager(): return _Mgr([world.HIM, world.HER, world.KID, world.STRANGER])
def object_manager(): return _Mgr([world.FRIDGE, world.BED, world.BED2, world.HIM._sim, world.HER._sim])
def get_persistence_service(): return _Persist()
def venue_service(): return _Venue()
def time_service(): return _Time()
def get_fire_service(): return FIRE
def game_clock_service(): return _Clock()
def get_instance_manager(kind): return _Tracks()
