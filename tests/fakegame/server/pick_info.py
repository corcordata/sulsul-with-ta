class PickType(object):
    PICK_SIM, PICK_OBJECT = 1, 2


class PickInfo(object):
    def __init__(self, pick_type=None, target=None, location=None, routing_surface=None):
        self.pick_type, self.target = pick_type, target
