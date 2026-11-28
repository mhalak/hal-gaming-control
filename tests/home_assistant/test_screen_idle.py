"""#92: deterministic Screen idle security, accounting and idempotency."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.components import mqtt

from custom_components.hal_gaming_control import foreground_source as src
from custom_components.hal_gaming_control.screen_idle import (
    DisplayGate, decode_display_context, STATE_TTL,
)
from custom_components.hal_gaming_control.screen_idle_bonus import (
    KEY, MAX_DAILY_MINUTES, maybe_add_screen_idle_grant, screen_idle_bonus_total,
)
from custom_components.hal_gaming_control.rule_engine import (
    effective_budget_limit, budget_overview,
)
from custom_components.hal_gaming_control.foreground_source import ForegroundSource

DEV = "pc1"
EPOCH = "a" * 32
RAW_EPOCH = "b" * 32
APP = {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}
T0 = datetime(2026, 11, 22, 16, tzinfo=timezone.utc).timestamp()


def display(ts, state, seq=1, *, device=DEV, epoch=EPOCH, age=0, idle=600000,
            ac=600, dc=300, source="ac"):
    return json.dumps({
        "version": 2, "device_id": device, "observed_at": ts,
        "display_state": state,
        "display_event_age_ms": age if state != "unknown" else None,
        "display_epoch": epoch if state != "unknown" else None,
        "display_sequence": seq if state != "unknown" else None,
        "display_scope": "windows_console",
        "ac_timeout_seconds": ac, "dc_timeout_seconds": dc,
        "power_source": source, "last_input_idle_ms": idle,
    })


def raw(ts, seq, *, state="foreground", device=DEV):
    return json.dumps({"version": 2, "device_id": device, "epoch": RAW_EPOCH,
                       "sequence": seq, "observed_at": ts, "state": state,
                       "process": APP["process"] if state == "foreground" else None,
                       "signature": None})


def now(ts=T0):
    return datetime.fromtimestamp(ts, timezone.utc)


def segments(t=T0, *, before=600, after=2):
    return [(t - before + 2, t - after, 'app-key')]


def receipt(t=T0, *, event_age_ms=0, idle_ms=600000, timeout=600):
    return json.loads(display(t, "off", seq=2, age=event_age_ms,
                              idle=idle_ms, ac=timeout))


def _gate(guest="pc1"):
    return DisplayGate(guest)


def test_strict_display_schema_no_retention_cross_pc_or_old_agent():
    packet = display(T0, "off", seq=3)
    assert decode_display_context(packet, DEV, retained=False, wall_now=T0)[
        "display_sequence"] == 3
    for payload,retained,dev,t in [
        (packet, True, DEV, T0), (packet, False, "pc2", T0),
        (packet, False, DEV, T0+10), (packet, False, DEV, T0-3),
        (packet.replace('"version": 2', '"version": 1'), False, DEV, T0),
        (packet.replace('"display_scope": "windows_console"',
                        '"display_scope": "monitor_proof"'), False, DEV, T0),
        ('{"version":2,"version":2}', False, DEV, T0),
        ('{' * 5000, False, DEV, T0),
        ("not json", False, DEV, T0),
    ]:
        with pytest.raises(ValueError):
            decode_display_context(payload, dev, retained=retained, wall_now=t)


@pytest.mark.parametrize("change", [
    {"display_event_age_ms": -1}, {"display_event_age_ms": True},
    {"display_epoch": "not-epoch"}, {"display_sequence": 0},
    {"display_sequence": True}, {"display_state": "OFF"},
    {"ac_timeout_seconds": True}, {"dc_timeout_seconds": -1},
    {"last_input_idle_ms": "123"}, {"power_source": "mains"},
    {"device_id": "pc2"},
])
def test_malformed_or_foreign_display_values_never_grant(change):
    data = json.loads(display(T0, "off"))
    data.update(change)
    with pytest.raises(ValueError):
        decode_display_context(json.dumps(data), DEV, retained=False, wall_now=T0)


def test_unknown_state_requires_no_fake_receipt():
    row = json.loads(display(T0, "unknown"))
    assert decode_display_context(json.dumps(row), DEV, retained=False,
                                  wall_now=T0)["display_state"] == "unknown"
    row["display_sequence"] = 123
    with pytest.raises(ValueError):
        decode_display_context(json.dumps(row), DEV, retained=False, wall_now=T0)


def test_gate_arms_after_on_and_only_fresh_ordered_off_counts():
    gate = _gate()
    ok, event = gate.observe(display(T0, "off", seq=1), retained=False,
                             wall_now=T0, monotonic_now=10)
    assert ok and event is None  # initial OFF is not a bonus!
    assert gate.current(10) == "off"
    ok, event = gate.observe(display(T0+1, "on", seq=2), retained=False,
                             wall_now=T0+1, monotonic_now=11)
    assert ok and event is None
    ok, event = gate.observe(display(T0+2, "dim", seq=3), retained=False,
                             wall_now=T0+2, monotonic_now=12)
    assert ok and event is None
    ok, event = gate.observe(display(T0+3, "off", seq=4, age=100),
                             retained=False, wall_now=T0+3, monotonic_now=13)
    assert ok and event and event["display_sequence"] == 4
    ok, event = gate.observe(display(T0+4, "off", seq=4, age=1100),
                             retained=False, wall_now=T0+4, monotonic_now=14)
    assert ok and event is None
    assert gate.current(14) == "off"
    ok, event = gate.observe(display(T0+3, "on", seq=3), retained=False,
                             wall_now=T0+5, monotonic_now=15)
    assert not ok and event is None
    assert gate.current(15) == "off"
    assert gate.current(14+STATE_TTL+1) == "unknown"


def test_same_display_receipt_must_not_change_from_on_to_off():
    gate = _gate()
    ok, event = gate.observe(display(T0, "on", seq=2), retained=False,
                             wall_now=T0, monotonic_now=10)
    assert ok and event is None
    ok, event = gate.observe(display(T0+1, "off", seq=2), retained=False,
                             wall_now=T0+1, monotonic_now=11)
    assert not ok and event is None
    assert gate.current(11) == "unknown"
    # An unchanged old ON after the invalidation must not re-arm a bonus.
    ok, event = gate.observe(display(T0+2, "on", seq=2), retained=False,
                             wall_now=T0+2, monotonic_now=12)
    assert ok and event is None
    ok, event = gate.observe(display(T0+3, "off", seq=3), retained=False,
                             wall_now=T0+3, monotonic_now=13)
    assert ok and event is None


def test_gate_restart_unknown_and_unsupported_epoch_fails_closed():
    gate = _gate()
    gate.observe(display(T0, "on", 1), retained=False,
                 wall_now=T0, monotonic_now=10)
    gate.invalidate()
    _, event = gate.observe(display(T0+1, "off", 2), retained=False,
                            wall_now=T0+1, monotonic_now=11)
    assert event is None
    gate.observe(display(T0+2, "on", 3), retained=False,
                 wall_now=T0+2, monotonic_now=12)
    _, event = gate.observe(display(T0+3, "off", 1, epoch="c"*32),
                            retained=False, wall_now=T0+3, monotonic_now=13)
    assert event is None  # new helper episode must re-arm with an ON.


def test_bonus_only_measured_before_off_with_timeout_evidence():
    options = {"enabled": True, "daily": 180, "weekly": 300}
    event = receipt()
    granted = maybe_add_screen_idle_grant(options, DEV, event, segments(), now())
    assert granted is not options
    assert granted[KEY]["events"][0]["id"] == EPOCH + ":2"
    assert screen_idle_bonus_total(granted, now()) == 9  # 596 verified sec -> 9 whole min
    assert effective_budget_limit(granted, now(), "daily") == 189
    assert effective_budget_limit(granted, now(), "weekly") == 300
    assert maybe_add_screen_idle_grant(granted, DEV, event, segments(), now()) is granted
    assert len(granted[KEY]["events"]) == 1
    assert options == {"enabled": True, "daily": 180, "weekly": 300}
    receipt_attrs = budget_overview(granted, {"daily": 120, "weekly": 120}, now(),
                                    ready=True)
    assert receipt_attrs["screen_idle_bonus_minutes"] == 9
    assert receipt_attrs["screen_idle_bonus_status"] == "automatic"
    assert receipt_attrs["daily_used_seconds"] == 120
    assert receipt_attrs["weekly_limit_minutes"] == 300


@pytest.mark.parametrize("changed", [
    {"last_input_idle_ms": 8000},  # manual OFF immediately after use
    {"last_input_idle_ms": None},  # no user-session evidence
    {"last_input_idle_ms": 2000000},  # cannot infer automatic off
    {"ac_timeout_seconds": 0},  # Windows set to Never
    {"ac_timeout_seconds": None},
    {"power_source": "unknown"},
    {"display_state": "dim"},
    {"device_id": "pc2"},
    {"display_scope": "monitor_proof"},
])
def test_never_grant_from_manual_unknown_or_wrong_device(changed):
    event = receipt()
    event.update(changed)
    opts = {"daily": 180}
    assert maybe_add_screen_idle_grant(opts, DEV, event, segments(), now()) is opts


def test_no_bonus_on_unverified_gaps_or_not_all_tracked():
    options = {}
    event = receipt()
    assert maybe_add_screen_idle_grant(
        options, DEV, event, [], now()) is options
    gap = [(T0-598, T0-350, "roblox"), (T0-300, T0-2, "roblox")]
    assert maybe_add_screen_idle_grant(
        options, DEV, event, gap, now()) is options
    short = [(T0-100, T0-2, "roblox")]
    assert maybe_add_screen_idle_grant(
        options, DEV, event, short, now()) is options


def test_midnight_and_clock_crossing_never_create_unassigned_bonus():
    options = {}
    off = datetime(2026, 11, 23, 0, 5, tzinfo=timezone.utc).timestamp()
    event = receipt(off)
    measured = segments(off)
    assert maybe_add_screen_idle_grant(
        options, DEV, event, measured, now(off)) is options


def test_missing_or_corrupt_journal_never_increases_allowance():
    opts = {}
    assert screen_idle_bonus_total(opts, now()) == 0
    corrupt = {KEY: {"version": 999, "device_id": DEV, "events": []}}
    assert screen_idle_bonus_total(corrupt, now()) == 0
    with pytest.raises(ValueError):
        maybe_add_screen_idle_grant(corrupt, DEV, receipt(), segments(), now())


def test_persistent_journal_survives_restart_and_daily_expiration():
    opts = {}
    one = maybe_add_screen_idle_grant(opts, DEV, receipt(), segments(), now())
    persisted = json.loads(json.dumps(one))
    assert maybe_add_screen_idle_grant(
        persisted, DEV, receipt(), segments(), now()) is persisted
    assert screen_idle_bonus_total(persisted, now(T0+86400)) == 0
    stale = dict(persisted, screen_idle_enabled=False)
    assert screen_idle_bonus_total(stale, now()) == 9  # obsolete toggle is inert
    assert len(stale[KEY]["events"]) == 1



@pytest.mark.asyncio
async def test_unknown_display_support_does_not_block_games_or_invent_bonus(hass):
    """Clean cut: PCs without Windows display events still count valid gameplay."""
    from pathlib import Path

    callbacks = {}
    async def subscribe(_hass, topic, callback, qos):
        callbacks[topic] = callback
        return lambda: None

    bonus = Mock()
    with patch.object(mqtt, "is_connected", return_value=True), \
         patch.object(mqtt, "async_subscribe_connection_status",
                      return_value=lambda: None), \
         patch.object(mqtt, "async_subscribe", side_effect=subscribe):
        source = ForegroundSource(hass, DEV, [APP], Mock(), on_screen_off=bonus)
        await source.async_start()
    root = f"SmartHouse/Gaming/{DEV}/"
    def deliver(suffix, payload, ts):
        message = SimpleNamespace(topic=root + suffix, payload=payload, retain=False)
        with patch.object(src, "time", return_value=ts), \
             patch.object(src, "monotonic", return_value=10000 + ts):
            callbacks[message.topic](message)

    deliver("discovery", json.dumps({"protocol_version": 1, "device_id": DEV,
            "name": "PC", "games": [], "actions": [],
            "unified_telemetry_protocol": 3}), 99)
    deliver("availability", "online", 99)
    fixture = (Path(__file__).resolve().parents[1] / "contracts" / "v3"
               / "telemetry-foreground.json")
    template = json.loads(fixture.read_text(encoding="utf-8"))

    def packet(ts, seq, display_state="unknown", event=1, edge=None):
        row = json.loads(json.dumps(template))
        row.update(device_id=DEV, observed_at=ts, sequence=seq)
        row["foreground"].update(process=APP["process"],
                                 signature=APP["signature"],
                                 state="foreground", sample_age_ms=0)
        d = row["display"]
        d["state"] = display_state
        if display_state == "unknown":
            d.update(event_epoch=None, event_sequence=None, event_age_ms=None,
                     sample_age_ms=None, last_input_idle_ms=None)
        else:
            d.update(event_epoch="b" * 32, event_sequence=event,
                     event_age_ms=int((ts - (edge if edge is not None else ts)) * 1000),
                     sample_age_ms=0, last_input_idle_ms=600000)
        return json.dumps(row)

    deliver("state/telemetry", packet(100, 1), 100)
    deliver("state/telemetry", packet(102, 2), 102)
    assert source.current(10102) == "Roblox"
    assert source.totals(now(102))["weekly"] > 0
    bonus.assert_not_called()

    deliver("state/telemetry", packet(104, 3, "on", event=1), 104)
    deliver("state/telemetry", packet(106, 4, "off", event=2), 106)
    stopped = source.totals(now(106))["weekly"]
    assert source.current(10106) == "idle"
    deliver("state/telemetry", packet(108, 5), 108)
    assert source.current(10108) is None
    assert source.totals(now(108))["weekly"] == stopped

    deliver("state/telemetry", packet(110, 6, "on", event=3), 110)
    assert source.current(10110) is None
    deliver("state/telemetry", packet(112, 7, "on", event=3, edge=110), 112)
    assert source.current(10112) == "Roblox"
    source.close()

@pytest.mark.asyncio
async def test_end_to_end_unified_v3_suppresses_off_charging_and_recovers_on(hass):
    """Screen Idle is always on but consumes only mandatory v3 telemetry."""
    from pathlib import Path

    callbacks, unsubscribed = {}, []

    async def subscribe(_hass, topic, callback, qos):
        callbacks[topic] = callback
        return lambda: unsubscribed.append(topic)

    changed, off_events = Mock(), Mock()
    with patch.object(mqtt, "is_connected", return_value=True), \
         patch.object(mqtt, "async_subscribe_connection_status",
                      return_value=lambda: unsubscribed.append("connection")), \
         patch.object(mqtt, "async_subscribe", side_effect=subscribe):
        source = ForegroundSource(
            hass, DEV, [APP], changed, on_screen_off=off_events)
        await source.async_start()
    root = f"SmartHouse/Gaming/{DEV}/"
    assert set(callbacks) == {
        root + "availability", root + "discovery", root + "state/telemetry"}
    fixture = (Path(__file__).resolve().parents[1] / "contracts" / "v3"
               / "telemetry-foreground.json")
    template = json.loads(fixture.read_text(encoding="utf-8"))

    def deliver(suffix, payload, ts, retain=False):
        msg = SimpleNamespace(topic=root + suffix, payload=payload,
                              retain=retain)
        with patch.object(src, "time", return_value=ts), \
             patch.object(src, "monotonic", return_value=10000 + ts):
            callbacks[msg.topic](msg)

    def snapshot(ts, seq, state="on", event=1, edge=100):
        packet = json.loads(json.dumps(template))
        packet.update(device_id=DEV, observed_at=ts, sequence=seq)
        packet["foreground"].update(
            process=APP["process"], signature=APP["signature"],
            state="foreground", sample_age_ms=0)
        packet["display"].update(
            state=state, event_sequence=event,
            event_epoch="b" * 32, event_age_ms=int((ts-edge) * 1000),
            sample_age_ms=0)
        return json.dumps(packet)

    deliver("discovery", json.dumps({
        "protocol_version": 1, "device_id": DEV, "name": "PC",
        "games": [], "actions": [], "unified_telemetry_protocol": 3}), 99)
    deliver("availability", "online", 99)
    deliver("state/telemetry", snapshot(100, 1), 100)
    deliver("state/telemetry", snapshot(102, 2, edge=100), 102)
    deliver("state/telemetry", snapshot(104, 3, edge=100), 104)
    before_off = source.totals(now(104))["weekly"]
    assert before_off > 0

    deliver("state/telemetry", snapshot(106, 4, state="off", event=2, edge=106), 106)
    assert source.current(10106) == "idle"
    assert off_events.call_count == 1
    assert source.last_raw is None
    deliver("state/telemetry", snapshot(108, 5, state="off", event=2, edge=106), 108)
    assert source.totals(now(108))["weekly"] == before_off

    deliver("state/telemetry", snapshot(110, 6, state="on", event=3, edge=110), 110)
    assert source.current(10110) is None
    deliver("state/telemetry", snapshot(112, 7, state="on", event=3, edge=110), 112)
    assert source.current(10112) == "Roblox"
    deliver("state/telemetry", snapshot(114, 8, state="on", event=3, edge=110), 114)
    assert source.totals(now(114))["weekly"] > before_off
    source._connection(False)
    assert source.current(10114) is None
    source.close()
    assert len(unsubscribed) == 4


def test_screen_idle_bonus_excludes_only_unlimited_overlap():
    from custom_components.hal_gaming_control.unlimited_bonus import record_override
    entire = record_override({}, DEV, now(T0 - 600), True)
    assert maybe_add_screen_idle_grant(entire, DEV, receipt(), segments(), now()) == entire
    half = record_override({}, DEV, now(T0 - 300), True)
    half = record_override(half, DEV, now(T0), False)
    granted = maybe_add_screen_idle_grant(half, DEV, receipt(), segments(), now())
    assert screen_idle_bonus_total(granted, now()) == 4
    later = record_override({}, DEV, now(T0 + 10), True)
    assert screen_idle_bonus_total(
        maybe_add_screen_idle_grant(later, DEV, receipt(), segments(), now()), now()) == 9
