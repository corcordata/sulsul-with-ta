import world


class _Msg(object):
    class _Inputs(list):
        def add(self):
            item = type('F', (), {})()
            self.append(item)
            return item

    def __init__(self):
        self.text_input = _Msg._Inputs()


class UiDialogTextInputOkCancel(object):
    def __init__(self, owner, title=None, text=None, **kwargs):
        self.owner, self.title, self.text = owner, title(), text()
        self.text_input_responses = {}
        self.accepted = False
        self._listeners = []

    @classmethod
    def TunableFactory(cls):
        outer = cls

        class _F(object):
            def default(self, owner, **kwargs):
                return outer(owner, **kwargs)
        return _F()

    def build_msg(self, **kwargs):
        return _Msg()

    def add_listener(self, fn):
        self._listeners.append(fn)

    def show_dialog(self, **kwargs):
        self.msg = self.build_msg()
        world.DIALOGS.append(self)

    def answer(self, text):
        """测试用：假装她打了字点确定。"""
        self.input_ok = self.on_text_input(self.msg.text_input[0].text_input_name, text)
        self.accepted = True
        for fn in self._listeners:
            fn(self)
