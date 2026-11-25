"""Wire, ordering and local presentation contract shared by MQTT+UI."""
import json
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gaming_control.popup_protocol import (
    PopupOrder, parse_popup, valid_event, make_event, validate_popup,
)
from gaming_control.popup_model import PopupModel, clock_text
from gaming_control.mqtt_bridge import Bridge

DEVICE = "pc1"


def cmd(*, seq=1, epoch="a" * 32, operation="upsert", now=None):
    packet = {
        "version": 1, "device_id": DEVICE,
        "producer_epoch": epoch, "sequence": seq,
        "issued_at": int(time.time()) if now is None else now,
        "message_ttl_seconds": 15, "display_stale_after_seconds": 120,
        "popup_id": "b" * 32, "operation": operation,
    }
    if operation == "upsert":
        packet["view"] = {
            "heading": "Gaming time remaining",
            "description": "Weekly budget",
            "remaining_seconds": 598, "progress_percent": 24,
            "buttons": [
                {"id": "ok", "text": "OK", "color": "neutral"},
                {"id": "more", "text": "Request more time", "color": "primary"},
            ],
        }
    return packet


def decode(packet, **kwargs):
    return parse_popup(json.dumps(packet).encode(), DEVICE, **kwargs)


@pytest.mark.parametrize("change", [
    lambda p: p.update(version=2),
    lambda p: p.update(device_id="other"),
    lambda p: p.update(issued_at=p["issued_at"] - 20),
    lambda p: p.update(message_ttl_seconds=0),
    lambda p: p.update(display_stale_after_seconds=0),
    lambda p: p.update(sequence=True),
    lambda p: p.update(producer_epoch="bad"),
    lambda p: p.update(popup_id="bad"),
    lambda p: p.update(operation="execute"),
    lambda p: p.update(extra="bad"),
    lambda p: p["view"].update(remaining_seconds=-1),
    lambda p: p["view"].update(remaining_seconds=True),
    lambda p: p["view"].update(progress_percent=float("nan")),
    lambda p: p["view"].update(progress_percent=101),
    lambda p: p["view"].update(heading="<script>"),
    lambda p: p["view"].update(description="bad\nnewline"),
    lambda p: p["view"].update(buttons=[{"id": "a", "text": "bad", "color": "rgb(0,0,0)"}]),
    lambda p: p["view"].update(buttons=[{"id": "same", "text": "A", "color": "primary"}] * 2),
    lambda p: p["view"].update(buttons=[{"id": str(i), "text": "A", "color": "primary"} for i in range(4)]),
])
def test_reject_invalid_popup_data(change):
    packet = deepcopy(cmd())
    change(packet)
    with pytest.raises(ValueError):
        decode(packet)


def test_reject_retained_duplicate_keys_and_oversized_payloads():
    with pytest.raises(ValueError):
        decode(cmd(), retained=True)
    raw = json.dumps(cmd()).replace('"sequence": 1', '"sequence": 1, "sequence": 2')
    with pytest.raises(ValueError):
        parse_popup(raw, DEVICE)
    with pytest.raises(ValueError):
        parse_popup(b"a" * 4097, DEVICE)


def test_hide_is_no_view_and_full_form_is_finite():
    hide = cmd(operation="hide")
    assert decode(hide)["operation"] == "hide"
    hide["view"] = cmd()["view"]
    with pytest.raises(ValueError):
        decode(hide)
    upsert = cmd()
    upsert["view"]["buttons"] = []
    upsert["view"]["progress_percent"] = 0.0
    upsert["view"]["remaining_seconds"] = 0
    assert decode(upsert)["view"]["remaining_seconds"] == 0


def test_epoch_sequence_replays_fail_without_reopening_closed_window():
    order = PopupOrder()
    assert order.accept(cmd(seq=1))
    assert not order.accept(cmd(seq=1))
    assert order.accept(cmd(seq=2))
    assert not order.accept(cmd(seq=1))
    newer = cmd(epoch="c" * 32, seq=1, now=int(time.time()) + 1)
    assert order.accept(newer)
    assert not order.accept(cmd(seq=99))
    order.reset()
    assert order.accept(cmd(seq=1))


def test_button_events_require_current_popup_and_exact_allowlist():
    packet = cmd()
    data = make_event(DEVICE, packet["popup_id"], "c" * 32, "button", "more")
    assert valid_event(data, packet, DEVICE)
    assert not valid_event(data | {"button_id": "new"}, packet, DEVICE)
    assert not valid_event(data | {"device_id": "other"}, packet, DEVICE)
    assert not valid_event(data | {"popup_id": "c" * 32}, packet, DEVICE)
    assert not valid_event(data | {"extra": 1}, packet, DEVICE)
    assert valid_event(make_event(DEVICE, packet["popup_id"], "d" * 32,
                                  "closed"), packet, DEVICE)


def test_visual_only_timer_reanchors_on_upsert_and_clamps_at_zero():
    current = [1000.]
    model = PopupModel(clock=lambda: current[0])
    p = cmd()
    model.upsert(p)
    assert model.snapshot()["time"] == "09:58"
    current[0] += 50
    snap = model.snapshot()
    assert snap["time"] == "09:08"
    assert snap["percent"] < 24
    assert snap["bar_color"] == "#ED646B"
    p = cmd(seq=2)
    p["view"]["remaining_seconds"] = 2100
    p["view"]["progress_percent"] = 75
    model.upsert(p)
    assert model.snapshot()["time"] == "35:00"
    assert model.snapshot()["bar_color"] == "#40C296"
    current[0] += 3000
    assert model.snapshot()["time"] == "00:00"
    assert model.snapshot()["percent"] == 0
    model.hide()
    assert model.snapshot() is None
    model.upsert(cmd(seq=3))
    assert model.snapshot()["time"] == "09:58"


@pytest.mark.parametrize("secs,text", [
    (0, "00:00"), (1, "00:01"), (59, "00:59"),
    (60, "01:00"), (3599, "59:59"), (3600, "1:00:00"),
    (86400, "24:00:00"), (-100, "00:00"),
])
def test_human_clock_format(secs, text):
    assert clock_text(secs) == text


def test_real_bridge_advertises_and_routes_popup_without_touching_v3():
    cfg = {"device": {"id": DEVICE, "name": "PC 1"},
           "mqtt": {"host": "localhost"}, "games": []}
    b = Bridge(cfg)
    b.client = Mock()
    b.client.publish.return_value.rc = 0
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.metadata["popup_ui_protocol"] == 1
    assert b.metadata["unified_telemetry_protocol"] == 3
    subscriptions = {c.args[0]: c.kwargs["options"]
                     for c in b.client.subscribe.call_args_list
                     if "options" in c.kwargs}
    topic = b.root + "/ui/popup"
    assert subscriptions[topic].QoS == 1
    assert subscriptions[topic].retainHandling == 2

    def send(packet, retained=False):
        b.on_message(b.client, None, SimpleNamespace(
            topic=topic, payload=json.dumps(packet).encode(), retain=retained))
    send(cmd(), True)
    assert list(b.drain_commands()) == []
    send(cmd())
    send(cmd())  # duplicate MQTT delivery must not reopen
    commands = list(b.drain_commands())
    assert len(commands) == 1 and commands[0][0] == "popup"
    send(cmd(seq=2, operation="hide"))
    assert [p[1]["operation"] for p in b.drain_commands()] == ["hide"]
    event = make_event(DEVICE, "b" * 32, "c" * 32, "closed")
    assert b.publish_popup_event(event)
    call = b.client.publish.call_args
    assert call.args[0] == b.root + "/ui/popup_event"
    assert call.kwargs["qos"] == 1 and call.kwargs["retain"] is False
    assert call.kwargs["properties"].MessageExpiryInterval == 15
    b.on_disconnect(b.client, None, None, None, None)
    assert not b.publish_popup_event(event)


def v2_fixture(name):
    from pathlib import Path
    packet = json.loads((Path(__file__).resolve().parents[2] / "tests" / "contracts" /
                         "v2" / ("popup-" + name + ".json")).read_text())
    packet["issued_at"] = int(time.time())
    return packet


def test_v2_shared_wire_and_independent_animation():
    initial = v2_fixture("upsert")
    refresh = v2_fixture("refresh")
    assert decode(initial) == initial
    assert decode(refresh) == refresh
    current = [1000.]
    model = PopupModel(clock=lambda: current[0])
    model.upsert(initial)
    assert model.snapshot()["time"] is None
    assert model.snapshot()["percent"] == 50
    current[0] += 900
    assert model.snapshot()["percent"] == 25
    assert model.refresh(refresh)
    current[0] += 20
    assert model.snapshot()["percent"] == 40
    model.hide()
    assert not model.refresh(refresh)
    assert model.snapshot() is None


def test_v2_real_bridge_rejects_invalid_refresh_and_accepts_shared_contract():
    cfg = {"device": {"id": DEVICE, "name": "PC 1"},
           "mqtt": {"host": "localhost"}, "games": []}
    b = Bridge(cfg)
    b.client = Mock()
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.metadata["popup_ui_protocols"] == [1, 2]
    for name in ("upsert", "refresh"):
        packet = v2_fixture(name)
        b.on_message(b.client, None, SimpleNamespace(
            topic=b.root + "/ui/popup", payload=json.dumps(packet).encode(), retain=False))
        assert list(b.drain_commands()) == [("popup", packet)]
    bad = v2_fixture("refresh")
    bad["sequence"] = 3
    bad["view"]["buttons"] = []
    with pytest.raises(ValueError):
        decode(bad)
    for fields in ({"countdown_running": True}, {"progress_seconds": 1},
                   {"progress_percent": 101, "progress_seconds": None}):
        bad["view"] = fields
        with pytest.raises(ValueError):
            decode(bad)
