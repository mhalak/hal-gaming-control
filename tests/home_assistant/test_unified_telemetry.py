"""Unified telemetry v3 (#176): exact schema, bounds and anti-replay contract."""
import json

import pytest

from custom_components.hal_gaming_control.unified_telemetry import (
    MAX_PACKET, TelemetryOrder, decode_telemetry, display_v2, foreground_v2,
)

DEVICE = "pc1"
P = "RobloxPlayerBeta.exe"
E1 = "a" * 32
E2 = "b" * 32


def sample(ts=100., seq=1, *, device=DEVICE, epoch=E1,
           fg="foreground", screen="on", fg_age=20, display_age=20):
    return {
        "version": 3, "device_id": device, "epoch": epoch, "sequence": seq,
        "observed_at": ts,
        "foreground": {"state": fg,
                       "process": P if fg == "foreground" else None,
                       "signature": None, "sample_age_ms": fg_age},
        "display": {
            "state": screen, "scope": "windows_console",
            "event_epoch": E2 if screen != "unknown" else None,
            "event_sequence": 1 if screen != "unknown" else None,
            "event_age_ms": 500 if screen != "unknown" else None,
            "sample_age_ms": display_age,
            "ac_timeout_seconds": 600, "dc_timeout_seconds": 300,
            "power_source": "ac", "last_input_idle_ms": 125000},
        "system": {"uptime_seconds": 9000, "agent_version": "0.2.12",
                   "agent_build_sha": None},
    }


def decode(row, *, now=None, retained=False, device=DEVICE):
    return decode_telemetry(
        json.dumps(row), device, retained=retained,
        wall_now=row["observed_at"] if now is None else now)


def test_valid_v3_and_exact_compatibility_shapes():
    v = decode(sample())
    assert json.loads(foreground_v2(v)) == {
        "version": 2, "device_id": DEVICE,
        "epoch": E1, "sequence": 1, "observed_at": 99.98,
        "state": "foreground", "process": P, "signature": None,
    }
    d = json.loads(display_v2(v))
    assert d["display_epoch"] == E2 and d["display_sequence"] == 1
    assert d["ac_timeout_seconds"] == 600
    assert v["system"]["uptime_seconds"] == 9000
    with_legacy = sample()
    with_legacy["legacy"] = {
        "in_game": "ON", "current_game": "Roblox",
        "active_game": "Roblox", "gaming_active": "ON",
        "focus_availability": "online"}
    assert "legacy" in decode(with_legacy)


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(version=2),
    lambda v: v.update(version=True),
    lambda v: v.update(device_id="pc2"),
    lambda v: v.update(epoch="not_hex"),
    lambda v: v.update(sequence=0),
    lambda v: v.update(sequence=True),
    lambda v: v.update(observed_at=float("nan")),
    lambda v: v.update(observed_at=float("inf")),
    lambda v: v.update(observed_at=-1),
    lambda v: v.update(secrets="no"),
    lambda v: v["foreground"].update(process="../secrets.exe"),
    lambda v: v["foreground"].update(state="running"),
    lambda v: v["foreground"].update(signature={"kind": "path", "value": "x"}),
    lambda v: v["foreground"].update(sample_age_ms=-1),
    lambda v: v["foreground"].update(sample_age_ms=True),
    lambda v: v["display"].update(scope="all_monitors"),
    lambda v: v["display"].update(event_sequence=True),
    lambda v: v["display"].update(event_age_ms=-1),
    lambda v: v["display"].update(ac_timeout_seconds=-1),
    lambda v: v["display"].update(dc_timeout_seconds=True),
    lambda v: v["display"].update(power_source="solar"),
    lambda v: v["display"].update(last_input_idle_ms=-1),
    lambda v: v["system"].update(uptime_seconds=True),
    lambda v: v["system"].update(agent_version="bad"),
    lambda v: v["system"].update(agent_build_sha="notsha"),
    lambda v: v["system"].update(username="private"),
    lambda v: v.update(legacy={"active_game": "Roblox"}),
])
def test_malformed_packets_never_pass_schema(mutation):
    row = sample()
    mutation(row)
    with pytest.raises(ValueError):
        decode(row)


def test_no_wrong_pc_retention_or_duplicate_json_keys():
    row = sample()
    for kwargs in [{"device": "pc2"}, {"retained": True},
                   {"now": 111}, {"now": 97}]:
        with pytest.raises(ValueError):
            decode(row, **kwargs)
    raw = json.dumps(row).replace('"version": 3', '"version": 3, "version": 3')
    with pytest.raises(ValueError):
        decode_telemetry(raw, DEVICE, retained=False, wall_now=100)
    with pytest.raises(ValueError):
        decode_telemetry("{" + '"a":1,' * 4000 + "}", DEVICE,
                         retained=False, wall_now=100)
    assert MAX_PACKET == 4096


def test_unknown_and_stale_samples_never_invent_game_or_monitor_proof():
    v = sample()
    v["foreground"].update(state="unknown", process=None,
                           signature=None, sample_age_ms=None)
    v["display"].update(state="unknown", event_epoch=None,
                        event_sequence=None, event_age_ms=None,
                        sample_age_ms=None)
    assert decode(v)["foreground"]["state"] == "unknown"
    assert decode(v)["display"]["state"] == "unknown"
    v["foreground"].update(state="idle", sample_age_ms=None)
    with pytest.raises(ValueError):
        decode(v)
    v = sample()
    v["foreground"]["sample_age_ms"] = 10100
    v["display"]["event_age_ms"] = 37000
    accepted = decode(v)
    assert accepted["foreground"]["state"] == "unknown"
    assert accepted["display"]["state"] == "unknown"
    assert json.loads(foreground_v2(accepted))["state"] == "unknown"
    assert json.loads(display_v2(accepted))["display_event_age_ms"] is None


def test_java_requires_stable_public_discriminator():
    v = sample()
    v["foreground"]["process"] = "javaw.exe"
    with pytest.raises(ValueError):
        decode(v)
    v["foreground"]["signature"] = {
        "kind": "java_class", "value": "net.minecraft.client.main.Main"}
    assert decode(v)["foreground"]["signature"]["kind"] == "java_class"
    v["foreground"]["state"] = "idle"
    with pytest.raises(ValueError):
        decode(v)


def test_display_unknown_requires_all_null_notification_fields():
    v = sample(screen="unknown")
    for key, value in [
        ("event_epoch", E2), ("event_sequence", 3), ("event_age_ms", 100),
    ]:
        bad = json.loads(json.dumps(v))
        bad["display"][key] = value
        with pytest.raises(ValueError):
            decode(bad)


def test_per_pc_epoch_order_replay_retirement_and_clock_rollback():
    gate = TelemetryOrder()
    first = decode(sample())
    assert gate.accept(first, monotonic_now=100)
    assert not gate.accept(first, monotonic_now=101)
    assert not gate.accept(decode(sample(101, 1)), monotonic_now=102)
    assert gate.accept(decode(sample(102, 2)), monotonic_now=103)
    gate.suspend()
    assert not gate.accept(decode(sample(104, 3)), monotonic_now=105)
    assert gate.accept(decode(sample(106, 1, epoch=E2)), monotonic_now=106)
    assert not gate.accept(decode(sample(101, 99, epoch=E1)), monotonic_now=107)
    assert not gate.accept(decode(sample(108, 2, epoch=E2)), monotonic_now=104)
    gate.suspend()
    assert not gate.accept(decode(sample(110, 3, epoch=E2)), monotonic_now=111)
