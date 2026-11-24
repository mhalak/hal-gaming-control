"""Windows popup helper liveness and IPC isolation tests (no desktop needed)."""
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys

import pytest

from gaming_control.popup_protocol import validate_popup
from gaming_control.popup_helper import PIPE_PREFIX, pipe_sddl
from gaming_control.popup_session import PopupSession
from gaming_control.popup_model import PopupModel


def packet(*, operation="upsert", remaining=598, seq=1):
    result = {
        "version": 1, "device_id": "pc1",
        "producer_epoch": "a" * 32,
        "sequence": seq, "issued_at": int(time.time()),
        "message_ttl_seconds": 15, "display_stale_after_seconds": 120,
        "popup_id": "b" * 32,
        "operation": operation,
    }
    if operation == "upsert":
        result["view"] = {
            "heading": "Gaming time remaining",
            "description": "Weekly budget", "remaining_seconds": remaining,
            "progress_percent": 24,
            "buttons": [{"id": "ok", "text": "OK", "color": "neutral"}],
        }
    return result


def test_popup_sid_acl_is_specific_and_no_pipe_paths_from_mqtt():
    sid = "S-1-5-21-1234-5678-9876-1001"
    assert pipe_sddl(sid) == "D:P(A;;GA;;;SY)(A;;0x0012019f;;;" + sid + ")"
    assert PIPE_PREFIX.startswith(r"\\.\pipe\HALGamingPopup-")
    for wrong in ("", "S-1-5", "Everyone", "S-1-5-21-" + "0" * 300):
        with pytest.raises(ValueError):
            pipe_sddl(wrong)


def test_handle_one_popup_and_hide_without_any_local_policy():
    session = PopupSession()
    value = packet()
    assert session.handle(value, "pc1")
    assert session.pending == value
    assert session.packet == value
    assert session.deadline > time.monotonic()
    second = packet(seq=2, remaining=300)
    assert session.handle(second, "pc1")
    assert session.packet == second
    assert session.handle(packet(operation="hide"), "pc1")
    assert session.packet is None
    assert session.pending is None
    assert session.handle(value, "pc2") is False


def test_pump_no_ui_on_broker_disconnect_or_locked_session():
    session = PopupSession()
    session.handle(packet(), "pc1")
    bridge = SimpleNamespace(connected=False, id="pc1")
    with patch("gaming_control.popup_session.selected_session") as select:
        session.pump(bridge)
        select.assert_not_called()
    assert session.packet is None
    session.handle(packet(), "pc1")
    bridge.connected = True
    with patch("gaming_control.popup_session.selected_session", return_value=(1, "locked")):
        session.pump(bridge)
    assert session.packet is None and session.pending is None
    assert session.process is None


def test_stale_popup_hides_instead_of_making_up_more_budget():
    session = PopupSession()
    session.handle(packet(), "pc1")
    session.deadline = 0.1
    bridge = SimpleNamespace(connected=True, id="pc1")
    with patch("gaming_control.popup_session.selected_session", return_value=(1, "unlocked")):
        session.pump(bridge)
    assert session.packet is None
    assert session.process is None


def test_popup_service_only_relays_when_correct_session_and_connected():
    session = PopupSession()
    session.handle(packet(), "pc1")
    bridge = SimpleNamespace(connected=True, id="pc1")
    event = SimpleNamespace(WAIT_TIMEOUT=258, WAIT_OBJECT_0=0,
                            WaitForSingleObject=Mock(return_value=258))
    with patch.dict(sys.modules, {"win32event": event}), \
         patch("gaming_control.popup_session.selected_session", return_value=(1, "unlocked")), \
         patch.object(session, "_start") as start, \
         patch.object(session, "_connect", return_value=True) as connect, \
         patch.object(session, "_events") as events, \
         patch.object(session, "_flush") as flush:
        # Mock a launched helper. Model and MQTT command are unchanged.
        def started(_session):
            session.process = Mock()
            session.session = 1
        start.side_effect = started
        session.pump(bridge)
        start.assert_called_once_with(1)
        connect.assert_called_once()
        events.assert_called_once_with(bridge)
        flush.assert_called_once()


def test_service_events_must_match_the_current_ha_popup_button_and_device():
    from gaming_control.popup_protocol import valid_event, make_event
    p = packet()
    click = make_event("pc1", p["popup_id"], "c" * 32, "button", "ok")
    assert valid_event(click, p, "pc1")
    assert not valid_event(click | {"button_id": "lock_pc"}, p, "pc1")
    assert not valid_event(click | {"device_id": "pc2"}, p, "pc1")
    assert not valid_event(click, None, "pc1")
