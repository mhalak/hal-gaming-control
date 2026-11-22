"""#92 read-only display telemetry: policy context never means screen OFF."""
import ctypes
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import paho.mqtt.client as mqtt

from gaming_control.display_context import (
    VIDEO_IDLE, VIDEO_SUBGROUP, MAX_INPUT_IDLE_MS,
    _guid, elapsed_input_ms, read_display_policy, read_interactive_input_idle_ms,
    SystemPowerStatus, LastInputInfo,
)
from gaming_control.focus_session import FocusProbe, helper_main, PIPE_PREFIX
from gaming_control.mqtt_bridge import Bridge


CONFIG = {"device": {"id": "pc1", "name": "PC 1"},
          "mqtt": {"host": "localhost"}, "games": []}


@pytest.mark.parametrize("ac,dc,source", [
    (600, 300, "ac"), (0, 0, "battery"), (120, 0, "unknown")])
def test_active_ac_dc_power_policy_without_changes(ac, dc, source):
    assert read_display_policy(lambda: (ac, dc, source)) == {
        "ac_timeout_seconds": ac, "dc_timeout_seconds": dc,
        "power_source": source}


@pytest.mark.parametrize("bad", [
    lambda: (_ for _ in ()).throw(OSError("access denied")),
    lambda: (True, 60, "ac"), lambda: (60, -1, "ac"),
    lambda: (60, 60, "AC"), lambda: (2**32, 1, "ac"),
])
def test_unavailable_policy_fails_closed_to_unknown(bad):
    assert read_display_policy(bad) == {
        "ac_timeout_seconds": None, "dc_timeout_seconds": None,
        "power_source": "unknown"}


def test_real_windows_guid_bytes_are_little_endian():
    assert bytes(_guid(VIDEO_SUBGROUP)) == __import__("uuid").UUID(VIDEO_SUBGROUP).bytes_le
    assert bytes(_guid(VIDEO_IDLE)) == __import__("uuid").UUID(VIDEO_IDLE).bytes_le


@pytest.mark.parametrize("now,last,expected", [
    (10000, 9000, 1000), (10000, 10000, 0),
    (0x100000032, 0xfffffff0, 66),
    (0x100000000, 0, 0),
    (MAX_INPUT_IDLE_MS + 1, 0, None),
    (2**32 + 10, 15, None),
    (-1, 0, None), (100, -1, None),
    (True, 0, None), (100, True, None),
])
def test_last_input_tick_wrap_and_invalid_or_old_observations(now, last, expected):
    assert elapsed_input_ms(now, last) == expected


def test_helper_getlastinputinfo_never_reports_failed_call():
    class Func:
        def __init__(self, cb):
            self.cb = cb
        def __call__(self, *args):
            return self.cb(*args)
    f = Func(lambda ptr: 0)
    user = SimpleNamespace(GetLastInputInfo=f)
    kernel = SimpleNamespace(GetTickCount64=Func(lambda: 10))
    def dll(name, **kwargs):
        return {"user32": user, "kernel32": kernel}[name]
    with patch("gaming_control.display_context.ctypes.WinDLL", dll, create=True):
        assert read_interactive_input_idle_ms() is None


def test_helper_getlastinputinfo_reports_only_age():
    class Func:
        def __init__(self, cb):
            self.cb = cb
        def __call__(self, *args):
            return self.cb(*args)
    def read(ptr):
        val = ctypes.cast(ptr, ctypes.POINTER(LastInputInfo)).contents
        assert val.cbSize == ctypes.sizeof(LastInputInfo)
        val.dwTime = 1000
        return True
    with patch("gaming_control.display_context.ctypes.WinDLL",
               side_effect=lambda name, **kw: {
                   "user32": SimpleNamespace(GetLastInputInfo=Func(read)),
                   "kernel32": SimpleNamespace(GetTickCount64=Func(lambda: 4000)),
               }[name], create=True):
        assert read_interactive_input_idle_ms() == 3000


def test_authenticated_interactive_helper_includes_input_age_without_content():
    handle = Mock()
    file = SimpleNamespace(CreateFile=Mock(return_value=handle),
                           WriteFile=Mock(side_effect=OSError("test stop")))
    pipe = SimpleNamespace(GetNamedPipeServerProcessId=Mock(return_value=123))
    with patch.dict("sys.modules", {
            "pywintypes": SimpleNamespace(error=OSError),
            "win32file": file, "win32pipe": pipe}), \
         patch("gaming_control.focus_session.sample_window",
               return_value={"time": 12.3, "status": "idle"}), \
         patch("gaming_control.focus_session.read_interactive_input_idle_ms",
               return_value=120000):
        assert helper_main(PIPE_PREFIX + "a" * 32, "123") != 0
    body = json.loads(file.WriteFile.call_args.args[1])
    assert body == {"time": 12.3, "status": "idle", "last_input_idle_ms": 120000}
    assert "username" not in body and "keys" not in body
    handle.Close.assert_called_once()


def test_focus_probe_invalidates_user_idle_on_lost_or_locked_session():
    p = FocusProbe()
    p.session, p.process = 1, Mock()
    p.started = time.monotonic()
    sample = {"time": time.monotonic(), "status": "idle",
              "last_input_idle_ms": 96000}
    with patch("gaming_control.focus_session.selected_session",
               return_value=(1, "unlocked")), \
         patch.object(p, "_report_child_exit", return_value=False), \
         patch.object(p, "_receive", return_value=sample):
        assert p.read([])["active_game"] == "idle"
    assert p.last_input_idle_ms == 96000
    with patch("gaming_control.focus_session.selected_session",
               return_value=(1, "locked")), patch.object(p, "close"):
        assert p.read([])["active_game"] == "idle"
    assert p.last_input_idle_ms is None


@pytest.mark.parametrize("idle", [True, 999999999, -1, "1000", None])
def test_focus_probe_never_exposes_invalid_idle(idle):
    p = FocusProbe()
    p.session, p.process = 1, Mock()
    p.started = time.monotonic()
    sample = {"time": time.monotonic(), "status": "idle",
              "last_input_idle_ms": idle}
    with patch("gaming_control.focus_session.selected_session",
               return_value=(1, "unlocked")), \
         patch.object(p, "_report_child_exit", return_value=False), \
         patch.object(p, "_receive", return_value=sample):
        p.read([])
    assert p.last_input_idle_ms is None


def linked_bridge():
    b = Bridge(CONFIG)
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.publish({"in_game": "OFF", "current_game": "idle"}, 10)
    b.client.publish.reset_mock()
    return b


def test_mqtt_display_context_is_nonretained_expiring_and_never_off():
    b = linked_bridge()
    context = b.capture_foreground_context()
    policy = {"ac_timeout_seconds": 600, "dc_timeout_seconds": 180,
              "power_source": "ac"}
    assert b.publish_display_context(policy, 120000, context)
    b.client.publish.assert_called_once()
    call = b.client.publish.call_args
    assert call.args[0] == b.root + "/state/display_context"
    assert call.kwargs["qos"] == 0 and call.kwargs["retain"] is False
    assert call.kwargs["properties"].MessageExpiryInterval == 45
    packet = json.loads(call.args[1])
    assert packet["device_id"] == "pc1"
    assert packet["display_state"] == "unknown"
    assert packet["last_input_idle_ms"] == 120000
    assert packet["ac_timeout_seconds"] == 600 and packet["dc_timeout_seconds"] == 180
    assert not b.publish_display_context(policy, 121000, context)
    b.client.publish.assert_called_once()


def test_mqtt_display_context_never_publishes_with_stale_or_disconnected_context():
    b = linked_bridge()
    context = b.capture_foreground_context()
    b.on_disconnect(b.client, None, None, None, None)
    assert not b.publish_display_context({"ac_timeout_seconds": 600,
                                          "dc_timeout_seconds": 600,
                                          "power_source": "ac"}, 0, context)
    assert b.client.publish.call_count == 0


def test_mqtt_invalid_policy_suppressed_no_privileged_action():
    b = linked_bridge()
    context = b.capture_foreground_context()
    assert not b.publish_display_context({"ac_timeout_seconds": True,
                                          "dc_timeout_seconds": 0,
                                          "power_source": "ac"}, 1, context)
    assert b.client.publish.call_count == 0


def test_mqtt_invalid_idle_fails_to_unknown_without_inventing_bonus():
    b = linked_bridge()
    context = b.capture_foreground_context()
    assert b.publish_display_context({"ac_timeout_seconds": None,
                                      "dc_timeout_seconds": None,
                                      "power_source": "unknown"}, True, context)
    packet = json.loads(b.client.publish.call_args.args[1])
    assert packet["last_input_idle_ms"] is None
    assert packet["display_state"] == "unknown"
