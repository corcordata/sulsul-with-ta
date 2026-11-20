"""假的游戏钟：一个数 = 一游戏分钟。"""


class TimeSpan(object):
    def __init__(self, ticks):
        self._ticks = ticks

    def in_minutes(self):
        return self._ticks


class DateAndTime(object):
    def __init__(self, ticks):
        self._ticks = ticks

    def __sub__(self, other):
        return TimeSpan(self._ticks - other.absolute_ticks())
