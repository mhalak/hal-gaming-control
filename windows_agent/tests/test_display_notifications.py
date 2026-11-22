"""#92: Windows console-power notifications, never physical-monitor proof."""
import ctypes
import json
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
import pytest

from gaming_control import display_notifications as D
from gaming_control.focus_session import FocusProbe
from gaming_control.mqtt_bridge import Bridge

CONFIG = {"device": {"id": "pc1", "name": "PC 1"},
          "mqtt": {"host": "localhost"}, "games": []}


def wire(value=0, *, guid=D.CONSOLE_DISPLAY_GUID, length=4):
    return (uuid.UUID(guid).bytes_le + length.to_bytes(4, "little")
            + value.to_bytes(4, "little"))


@pytest.mark.parametrize("value,expected", [
    (0, "off"), (1, "on"), (2, "dim"),
    (3, "unknown"), (0xffffffff, "unknown")])
def test_console_power_states_are_explicit_values(value, expected):
    assert D.decode_console_display_event(wire(value)) == expected


def test_foreign_or_malformed_notifications_do_not_claim_off():
    assert D.decode_console_display_event(
        wire(guid="11111111-2222-3333-4444-555555555555")) is None
    assert D.decode_console_display_event(wire(length=8)) == "unknown"
    assert D.decode_console_display_event(wire()[:20]) == "unknown"
    assert D.decode_console_display_event(b"") == "unknown"
    assert D.decode_console_display_event("on") == "unknown"


def test_tracker_requires_event_and_expires_after_age_limit():
    clock = Mock(return_value=10.0)
    model = D.DisplayStateTracker(clock=clock)
    assert model.snapshot() == {"display_state": "unknown", "display_event_age_ms": None,
            "display_epoch": None, "display_sequence": None}
    assert model.receive(wire(0))
    assert model.snapshot()["display_sequence"] == 1
    clock.return_value = 11.25
    assert model.snapshot() == {"display_state": "off", "display_event_age_ms": 1250}
    model.receive(wire(1))
    assert model.snapshot()["display_sequence"] == 2
    assert model.snapshot()["display_state"] == "on"
    model.receive(wire(2))
    assert model.snapshot()["display_state"] == "dim"
    model.invalidate()
    assert model.snapshot()["display_state"] == "unknown"
    clock.return_value = 20
    model.receive(wire(0))
    clock.return_value = 20 + D.MAX_EVENT_AGE_MS / 1000 + 1
    assert model.snapshot() == {"display_state": "unknown", "display_event_age_ms": None,
            "display_epoch": None, "display_sequence": None}


def test_tracker_ignores_foreign_event_and_invalidates_bad_event_and_clock():
    clock = Mock(return_value=10)
    model = D.DisplayStateTracker(clock=clock)
    assert model.receive(wire(0))
    assert not model.receive(wire(1, guid="11111111-2222-3333-4444-555555555555"))
    assert model.snapshot()["display_state"] == "off"
    assert model.receive(wire(length=99))
    assert model.snapshot()["display_state"] == "unknown"
    assert model.receive(wire(0))
    clock.return_value = 9
    assert model.snapshot()["display_state"] == "unknown"


def test_wndproc_handles_only_windows_power_messages():
    tracker = D.DisplayStateTracker(clock=lambda: 10)
    observer = D.DisplayObserver(tracker=tracker)
    with patch.object(D.ctypes, "string_at", return_value=wire(0)) as getter:
        assert observer._wndproc(42, D.WM_POWERBROADCAST,
                                 D.PBT_POWERSETTINGCHANGE, 123) == 1
    getter.assert_called_once_with(123, 24)
    assert tracker.snapshot()["display_state"] == "off"
    with patch.dict(sys.modules, {"win32gui": SimpleNamespace(DefWindowProc=Mock(return_value=0))}):
        assert observer._wndproc(42, D.WM_DISPLAYCHANGE, 0, 0) == 0
    assert tracker.snapshot()["display_state"] == "unknown"
    for event in [D.PBT_APMSUSPEND, D.PBT_APMRESUMEAUTOMATIC,
                  D.PBT_APMRESUMESUSPEND]:
        tracker.receive(wire(0))
        assert observer._wndproc(42, D.WM_POWERBROADCAST, event, 0) == 1
        assert tracker.snapshot()["display_state"] == "unknown"
    tracker.receive(wire(0))
    observer._wndproc(42, D.WM_POWERBROADCAST, D.PBT_POWERSETTINGCHANGE, 0)
    assert tracker.snapshot()["display_state"] == "unknown"


def test_hidden_window_lifecycle_and_correct_notification_registration():
    klass = SimpleNamespace(hInstance=None, lpszClassName=None, lpfnWndProc=None)
    gui = SimpleNamespace(WNDCLASS=Mock(return_value=klass), RegisterClass=Mock(),
                          CreateWindowEx=Mock(return_value=77),
                          DestroyWindow=Mock(), UnregisterClass=Mock(),
                          PumpWaitingMessages=Mock(return_value=0))
    api = SimpleNamespace(GetModuleHandle=Mock(return_value=42))
    register = Mock(return_value=123)
    unregister = Mock(return_value=True)
    user = SimpleNamespace(RegisterPowerSettingNotification=register,
                           UnregisterPowerSettingNotification=unregister)
    with patch.dict(sys.modules, {"win32api": api, "win32gui": gui}), \
         patch.object(ctypes, "WinDLL", return_value=user, create=True):
        observer = D.DisplayObserver()
        assert observer.start()
        assert observer.start()  # idempotent
        assert gui.CreateWindowEx.call_args.args[3] == 0  # no visible style
        assert register.call_args.args[0] == 77
        assert register.call_args.args[2] == 0  # DEVICE_NOTIFY_WINDOW
        assert observer.sample()["display_state"] == "unknown"
        observer.pump()
        observer.close()
        observer.close()
    register.assert_called_once()
    unregister.assert_called_once_with(123)
    gui.DestroyWindow.assert_called_once_with(77)


def test_registration_failure_does_not_break_existing_focus_probe():
    gui = SimpleNamespace(WNDCLASS=Mock(), RegisterClass=Mock(),
                          CreateWindowEx=Mock(side_effect=OSError("no desktop")),
                          UnregisterClass=Mock(), DestroyWindow=Mock())
    api = SimpleNamespace(GetModuleHandle=Mock(return_value=42))
    with patch.dict(sys.modules, {"win32api": api, "win32gui": gui}):
        observer = D.DisplayObserver()
        assert not observer.start()
    assert observer.sample() == {"display_state": "unknown",
                                 "display_event_age_ms": None}


def test_helper_freshness_and_lock_reset_display_state():
    p = FocusProbe()
    p.session, p.process = 1, Mock()
    p.started = time.monotonic()
    sample = {"time": time.monotonic(), "status": "idle",
              "display_state": "off", "display_event_age_ms": 100,
              "display_epoch": "a" * 32, "display_sequence": 1}
    with patch("gaming_control.focus_session.selected_session",
               return_value=(1, "unlocked")), \
         patch.object(p, "_report_child_exit", return_value=False), \
         patch.object(p, "_receive", side_effect=[sample, None]):
        assert p.read([])["active_game"] == "idle"
        assert p.display_state == "off"
        p.read([])
        assert p.display_state == "unknown"
    with patch("gaming_control.focus_session.selected_session",
               return_value=(1, "locked")), patch.object(p, "close"):
        assert p.read([])["active_game"] == "idle"
    assert p.display_state == "unknown"


def test_stale_helper_sample_cannot_claim_display_off():
    p = FocusProbe()
    p.session, p.process = 1, Mock()
    p.started = time.monotonic()
    sample = {"time": time.monotonic() - 20, "status": "idle",
              "display_state": "off", "display_event_age_ms": 100,
              "display_epoch": "a" * 32, "display_sequence": 1}
    with patch("gaming_control.focus_session.selected_session",
               return_value=(1, "unlocked")), \
         patch.object(p, "_report_child_exit", return_value=False), \
         patch.object(p, "_receive", return_value=sample):
        p.read([])
    assert p.display_state == "unknown"


def live_bridge():
    b = Bridge(CONFIG)
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.publish({"in_game": "OFF", "current_game": "idle"}, 10)
    b.client.publish.reset_mock()
    return b


def policy():
    return {"ac_timeout_seconds": 600, "dc_timeout_seconds": 120,
            "power_source": "ac"}


def test_one_mqtt_json_includes_screen_state_and_timeout_not_extra_entities():
    b = live_bridge()
    ctx = b.capture_foreground_context()
    assert b.publish_display_context(policy(), 120000, ctx,
                                     display_state="off", display_event_age_ms=500,
                                     display_epoch="a" * 32, display_sequence=1)
    assert b.client.publish.call_count == 1
    call = b.client.publish.call_args
    assert call.args[0] == b.root + "/state/display_context"
    assert call.kwargs["qos"] == 0 and not call.kwargs["retain"]
    assert call.kwargs["properties"].MessageExpiryInterval == 45
    data = json.loads(call.args[1])
    assert data["display_state"] == "off" and data["display_event_age_ms"] == 500
    assert data["ac_timeout_seconds"] == 600
    assert data["dc_timeout_seconds"] == 120
    assert data["display_scope"] == "windows_console"
    assert data["version"] == 2
    assert data["display_epoch"] == "a" * 32 and data["display_sequence"] == 1
    assert not b.publish_display_context(policy(), 120001, ctx,
                                         display_state="off", display_event_age_ms=501,
                                         display_epoch="a" * 32, display_sequence=1)
    assert b.publish_display_context(policy(), 120002, ctx,
                                     display_state="on", display_event_age_ms=1,
                                     display_epoch="a" * 32, display_sequence=2)
    assert b.client.publish.call_count == 2


@pytest.mark.parametrize("state,age,expected", [
    ("off", True, "unknown"), ("off", -1, "unknown"),
    ("off", None, "unknown"), ("OFF", 5, "unknown"),
    ("off", D.MAX_EVENT_AGE_MS + 1, "unknown"),
    ("dim", 1500, "dim"), ("on", 0, "on")])
def test_invalid_untrusted_state_cannot_claim_power_off(state, age, expected):
    b = live_bridge()
    ctx = b.capture_foreground_context()
    assert b.publish_display_context(policy(), None, ctx,
                                     display_state=state, display_event_age_ms=age,
                                     display_epoch="a" * 32, display_sequence=1)
    msg = json.loads(b.client.publish.call_args.args[1])
    assert msg["display_state"] == expected


def test_reconnect_invalidates_previous_power_state():
    b = live_bridge()
    ctx = b.capture_foreground_context()
    assert b.publish_display_context(policy(), 5, ctx,
                                     display_state="off", display_event_age_ms=1,
                                     display_epoch="a" * 32, display_sequence=1)
    b.client.publish.reset_mock()
    b.on_disconnect(b.client, None, None, None, None)
    assert not b.publish_display_context(policy(), 5, ctx,
                                         display_state="off", display_event_age_ms=1,
                                         display_epoch="a" * 32, display_sequence=1)
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.publish({"in_game": "OFF", "current_game": "idle"}, 11)
    b.client.publish.reset_mock()
    current = b.capture_foreground_context()
    assert b.publish_display_context(policy(), 5, current)
    assert json.loads(b.client.publish.call_args.args[1])["display_state"] == "unknown"
