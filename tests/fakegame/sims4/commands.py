REGISTERED = {}


class CommandType(object):
    Live = 5


class CheatOutput(object):
    lines = []

    def __init__(self, connection):
        pass

    def __call__(self, text):
        CheatOutput.lines.append(text)


def Command(*aliases, **kwargs):
    def deco(fn):
        for alias in aliases:
            REGISTERED[alias] = fn
        return fn
    return deco


CLIENT_CHEATS = []


def client_cheat(text, context):
    CLIENT_CHEATS.append(text)
