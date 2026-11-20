import world


class _Dialog(object):
    def __init__(self, owner, title, text):
        self.title, self.text = title(), text()

    def show_dialog(self, icon_override=None, **kwargs):
        world.NOTIFICATIONS.append((self.title, self.text, icon_override is not None))


class _Factory(object):
    def default(self, owner, title=None, text=None, **kwargs):
        return _Dialog(owner, title, text)


class UiDialogNotification(object):
    @staticmethod
    def TunableFactory():
        return _Factory()
