"""Exercise the actual fixed-form Tk renderer without a physical display.

These fakes deliberately model widget lifetime and the message pipe, so the
security/IPC code and presentation logic are covered on CI (Linux + Windows).
"""
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gaming_control.popup_helper import _PopupWindow, popup_helper_main, PIPE_PREFIX
from gaming_control.popup_protocol import make_event


class Widget:
    def __init__(self, parent=None, *args, **kwargs):
        self.parent = parent
        self.args, self.props = args, kwargs
        self.children = []
        self.destroyed = False
        self.cmds = []
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def pack(self, **kwargs):
        self.pack_args = kwargs
        return self

    def grid(self, **kwargs):
        self.grid_args = kwargs
        return self

    def configure(self, **kwargs):
        self.props.update(kwargs)

    def winfo_children(self):
        return [c for c in self.children if not c.destroyed]

    def grid_columnconfigure(self, col, **kwargs):
        self.cmds.append(("column", col, kwargs))

    def destroy(self):
        self.destroyed = True

    def create_rectangle(self, *args, **kwargs):
        self.cmds.append(("rectangle", args, kwargs))
        return 1

    def create_oval(self, *args, **kwargs):
        self.cmds.append(("oval", args, kwargs))
        return 2

    def coords(self, *args):
        self.cmds.append(("coords", args))

    def itemconfigure(self, *args, **kwargs):
        self.cmds.append(("itemconfigure", args, kwargs))

    def winfo_width(self):
        return 355


class Root(Widget):
    def __init__(self):
        super().__init__()
        self.visible = False
        self.closed = False
        self.after_calls = []

    def title(self, title):
        self.title_text = title

    def resizable(self, *args):
        pass

    def geometry(self, geometry):
        self.geometry_text = geometry

    def protocol(self, kind, callback):
        self.close_callback = callback

    def withdraw(self):
        self.visible = False

    def deiconify(self):
        self.visible = True

    def state(self):
        return "normal" if self.visible else "withdrawn"

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))

    def quit(self):
        self.closed = True

    def mainloop(self):
        pass


class Pipe:
    def __init__(self):
        self.inbound, self.outbound = [], []

    def peek(self, _pipe, _len):
        return None, len(self.inbound[0]) if self.inbound else 0, None

    def read(self, _pipe, _maxlen):
        return 0, self.inbound.pop(0)

    def write(self, _pipe, data):
        self.outbound.append(data)
        return 0, len(data)


def packet(seq=1, *, operation="upsert", buttons=2, remaining=598):
    result = {
        "version": 1, "device_id": "pc1", "producer_epoch": "a"*32,
        "sequence": seq, "issued_at": int(time.time()),
        "message_ttl_seconds": 15, "display_stale_after_seconds": 120,
        "popup_id": "b"*32, "operation": operation,
    }
    if operation == "upsert":
        result["view"] = {
            "heading": "Gaming time remaining", "description": "Weekly budget",
            "remaining_seconds": remaining, "progress_percent": 24,
            "buttons": [{"id":f"option{i}","text":f"Option {i}","color":"primary"}
                        for i in range(buttons)],
        }
    return result


def fake_gui():
    root, pipe = Root(), Pipe()
    tk = SimpleNamespace(Frame=Widget, Canvas=Widget, Label=Widget,
                         Button=Widget)
    win32file = SimpleNamespace(ReadFile=pipe.read, WriteFile=pipe.write)
    win32pipe = SimpleNamespace(PeekNamedPipe=pipe.peek)
    ui = _PopupWindow(root, tk, pipe, "pc1", win32file, win32pipe)
    return ui, root, pipe


def test_fixed_theme_and_equal_dynamic_buttons_stay_in_same_window():
    ui, root, _ = fake_gui()
    assert root.title_text == "HAL Gaming Control"
    assert root.geometry_text == "420x300"
    assert root.visible is False
    assert root.after_calls
    assert ui.actions.winfo_children() == []
    ui._upsert(packet())
    assert root.visible
    assert ui.heading.props["text"] == "Gaming time remaining"
    assert ui.clock.props["text"] == "09:58"
    assert len(ui.actions.winfo_children()) == 2
    # In-place refresh doesn't raise a new window; both original buttons die.
    old = ui.actions.winfo_children()
    root.deiconify = Mock()
    ui._upsert(packet(seq=2, buttons=3, remaining=120))
    root.deiconify.assert_not_called()
    assert len(ui.actions.winfo_children()) == 3
    assert all(widget.destroyed for widget in old)
    # The grid columns all share a single equal-width group.
    for widget in ui.actions.winfo_children():
        assert widget.grid_args["sticky"] == "ew"
    ui._upsert(packet(seq=3, buttons=0, remaining=0))
    assert not ui.actions.winfo_children()
    assert ui.clock.props["text"] == "00:00"
    assert any(a[0]=="itemconfigure" for a in ui.bar.cmds)


def test_close_then_new_upsert_reopens_and_reports_only_response_ids():
    ui, root, pipe = fake_gui()
    ui._upsert(packet())
    buttons = ui.actions.winfo_children()
    buttons[0].props["command"]()
    assert json.loads(ui.pending[-1])["button_id"] == "option0"
    ui._closed()
    assert not root.visible
    assert json.loads(ui.pending[-1])["kind"] == "closed"
    ui._upsert(packet(seq=2))
    assert root.visible
    ui._press("option1")
    assert json.loads(ui.pending[-1])["button_id"] == "option1"


def test_real_ipc_poll_displays_hides_and_reports_button_event():
    ui, root, pipe = fake_gui()
    import types
    with patch.dict(sys.modules, {"pywintypes": types.SimpleNamespace(error=RuntimeError)}):
        pipe.inbound.append(json.dumps(packet()).encode())
        ui._poll()
        assert root.visible
        assert ui.pending == []
        ui.actions.winfo_children()[1].props["command"]()
        ui._poll()
        assert len(pipe.outbound) == 1
        assert json.loads(pipe.outbound[0])["button_id"] == "option1"
        pipe.inbound.append(json.dumps(packet(seq=2,operation="hide")).encode())
        ui._poll()
        assert root.visible is False
        pipe.inbound.append(json.dumps(packet(seq=3)).encode())
        ui._poll()
        assert root.visible is True
        assert len(root.after_calls) == 5


def test_malformed_service_frame_does_not_execute_and_closes_helper():
    ui, root, pipe = fake_gui()
    import types
    with patch.dict(sys.modules, {"pywintypes": types.SimpleNamespace(error=RuntimeError)}):
        pipe.inbound.append(b'{"version":99}')
        ui._poll()
    assert ui.dead
    assert root.closed
    assert not root.visible


def test_popup_helper_rejects_bad_arguments_before_any_windows_pipe():
    import types
    modules = {"win32file": Mock(), "win32pipe": Mock(),
               "pywintypes": types.SimpleNamespace(error=RuntimeError)}
    with patch.dict(sys.modules, modules):
        assert popup_helper_main("bad-pipe", "11", "pc1") == 2
        assert popup_helper_main(PIPE_PREFIX+"a"*32, "-1", "pc1") == 2
        assert popup_helper_main(PIPE_PREFIX+"a"*32, "11", "bad/device") == 2
    modules["win32file"].CreateFile.assert_not_called()


def test_popup_helper_rejects_wrong_server_pid_without_opening_window():
    import types
    handle = Mock()
    files = SimpleNamespace(CreateFile=Mock(return_value=handle))
    pipe = SimpleNamespace(GetNamedPipeServerProcessId=Mock(return_value=999))
    modules = {"win32file":files, "win32pipe":pipe,
               "pywintypes":types.SimpleNamespace(error=RuntimeError)}
    with patch.dict(sys.modules, modules):
        assert popup_helper_main(PIPE_PREFIX+"a"*32,"123","pc1") == 3
    handle.Close.assert_called_once()



def test_popup_helper_launches_fixed_theme_with_verified_system_pipe():
    import types
    root = Root()
    handle = Mock()
    files = SimpleNamespace(CreateFile=Mock(return_value=handle))
    pipe = SimpleNamespace(
        GetNamedPipeServerProcessId=Mock(return_value=123),
        SetNamedPipeHandleState=Mock(), PIPE_READMODE_MESSAGE=2,
        PeekNamedPipe=Mock(return_value=(None, 0, None)))
    tk = SimpleNamespace(Tk=lambda: root, Frame=Widget, Canvas=Widget,
                         Label=Widget, Button=Widget)
    modules = {
        "win32file": files, "win32pipe": pipe, "tkinter": tk,
        "pywintypes": types.SimpleNamespace(error=RuntimeError),
    }
    with patch.dict(sys.modules, modules):
        result = popup_helper_main(PIPE_PREFIX + "a" * 32, "123", "pc1")
    assert result == 0
    assert root.title_text == "HAL Gaming Control"
    assert root.destroyed
    assert root.after_calls
    files.CreateFile.assert_called_once()
    pipe.SetNamedPipeHandleState.assert_called_once()
    handle.Close.assert_called_once()


def test_popup_helper_open_failure_cannot_create_a_desktop_window():
    import types
    files = SimpleNamespace(CreateFile=Mock(side_effect=OSError("denied")))
    tk = SimpleNamespace(Tk=Mock())
    modules = {
        "win32file": files, "win32pipe": Mock(), "tkinter": tk,
        "pywintypes": types.SimpleNamespace(error=RuntimeError),
    }
    with patch.dict(sys.modules, modules):
        assert popup_helper_main(PIPE_PREFIX + "a" * 32, "123", "pc1") == 4
    tk.Tk.assert_not_called()


def test_v2_hidden_fields_and_refresh_never_reopens_dismissed_popup():
    from test_popup_protocol import v2_fixture
    ui, root, pipe = fake_gui()
    initial, refresh = v2_fixture("upsert"), v2_fixture("refresh")
    import types
    with patch.dict(sys.modules, {"pywintypes": types.SimpleNamespace(error=RuntimeError)}):
        pipe.inbound.append(json.dumps(initial).encode())
        ui._poll()
        assert root.visible and ui.clock.props["text"] == ""
        assert ui.percent.props["text"] == "50% remaining"
        pipe.inbound.append(json.dumps(refresh).encode())
        ui._poll()
        assert ui.percent.props["text"] == "40% remaining"
        ui._closed()
        pipe.inbound.append(json.dumps(refresh).encode())
        ui._poll()
        assert not root.visible
        initial["sequence"] = 3
        initial["view"].update(remaining_seconds=60, countdown_running=False,
                               progress_percent=None, progress_seconds=None)
        pipe.inbound.append(json.dumps(initial).encode())
        ui._poll()
        assert root.visible and ui.clock.props["text"] == "01:00"
        assert ui.percent.props["text"] == ""
