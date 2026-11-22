from custom_components.hal_gaming_control.liveness import UptimeLiveness

def test_retained_value_not_fresh():
    live = UptimeLiveness()
    assert not live.observe("100", 0)
    assert not live.observe("100", 5)
    assert live.observe("160", 60)
    assert live.observe("160", 149)
    assert not live.observe("160", 150)
    assert live.observe("280", 180)

def test_unavailable_reconnect_and_reboot():
    live = UptimeLiveness()
    assert not live.observe("100", 0)
    assert live.observe("160", 60)
    assert not live.observe("unavailable", 61)
    assert not live.observe("160", 62)
    assert live.observe("220", 120)
    assert live.observe("5", 125)
    assert not live.observe(None, 126)


# The new source is an atomic, non-retained packet, not a combination of
# legacy retained states. No HA runtime or Windows publication is wired yet.
import json

import pytest


def foreground_gate():
    from custom_components.hal_gaming_control.foreground_snapshot import ForegroundLiveness
    return ForegroundLiveness("pc1", {"Roblox", "Minecraft"})


def packet(**changes):
    data = {"version": 1, "device_id": "pc1", "epoch": "a" * 32,
            "sequence": 1, "observed_at": 1000.0,
            "active_game": "Roblox", "gaming_active": "ON"}
    return json.dumps(data | changes)


def observe(gate, payload=None, *, retained=False, wall=1000.0, mono=100.0):
    return gate.observe(packet() if payload is None else payload, retained=retained,
                        wall_now=wall, monotonic_now=mono)


def test_foreground_snapshot_accepts_one_fresh_atomic_state():
    gate = foreground_gate()
    assert gate.current(100) is None
    assert observe(gate)
    assert gate.current(100) == "Roblox"
    assert observe(gate, packet(sequence=2, observed_at=1001, active_game="Minecraft"),
                   wall=1001, mono=101)
    assert gate.current(101) == "Minecraft"


def test_foreground_snapshot_retained_never_establishes_freshness():
    gate = foreground_gate()
    assert not observe(gate, retained=True)
    assert gate.current(100) is None
    assert observe(gate)
    assert not observe(gate, packet(sequence=2, observed_at=1001), retained=True,
                       wall=1001, mono=101)
    assert gate.current(110) is None


def test_foreground_snapshot_duplicate_does_not_renew_expiry():
    gate = foreground_gate()
    assert observe(gate)
    assert not observe(gate, wall=1009, mono=109)
    assert gate.current(109) == "Roblox"
    assert gate.current(110) is None


def test_foreground_snapshot_age_deducted_from_remaining_lifetime():
    gate = foreground_gate()
    assert observe(gate, wall=1008, mono=100)
    assert gate.current(101.99) == "Roblox"
    assert gate.current(102) is None


@pytest.mark.parametrize("observed_at", [990, 1002.01])
def test_foreground_snapshot_rejects_old_or_future_timestamp(observed_at):
    gate = foreground_gate()
    assert not observe(gate, packet(observed_at=observed_at))
    assert gate.current(100) is None


def test_foreground_snapshot_reconnect_invalidates_and_keeps_replay_watermark():
    gate = foreground_gate()
    assert observe(gate)
    gate.invalidate()
    assert gate.current(101) is None
    assert not observe(gate, wall=1001, mono=101)
    assert gate.current(101) is None
    assert observe(gate, packet(sequence=2, observed_at=1002), wall=1002, mono=102)
    assert gate.current(102) == "Roblox"


def test_foreground_snapshot_epoch_restart_and_old_epoch_replay():
    gate = foreground_gate()
    assert observe(gate, packet(sequence=10))
    assert observe(gate, packet(epoch="b" * 32, sequence=1, observed_at=1001),
                   wall=1001, mono=101)
    assert not observe(gate, packet(sequence=11, observed_at=1000.5),
                       wall=1002, mono=102)
    assert gate.current(102) == "Roblox"


def test_foreground_snapshot_rejects_out_of_order_in_same_epoch():
    gate = foreground_gate()
    assert observe(gate, packet(sequence=5))
    assert not observe(gate, packet(sequence=4, observed_at=1001), wall=1001, mono=101)
    assert gate.current(101) == "Roblox"


def test_foreground_snapshot_idle_and_unknown_are_distinct():
    gate = foreground_gate()
    assert observe(gate, packet(active_game="idle", gaming_active="OFF"))
    assert gate.current(100) == "idle"
    assert observe(gate, packet(sequence=2, observed_at=1001, active_game="unknown",
                                gaming_active="UNKNOWN"), wall=1001, mono=101)
    assert gate.current(101) is None


@pytest.mark.parametrize("changes", [
    {"version": True}, {"version": 2}, {"device_id": "pc2"},
    {"epoch": "invalid"}, {"sequence": True}, {"sequence": 0},
    {"observed_at": float("nan")}, {"observed_at": "1000"},
    {"active_game": "Roblox | Minecraft"}, {"active_game": "Unenrolled"},
    {"active_game": "idle"}, {"gaming_active": "OFF"},
    {"active_game": "unknown"}, {"gaming_active": "UNKNOWN"},
])
def test_foreground_snapshot_invalid_packet_fails_closed(changes):
    gate = foreground_gate()
    assert observe(gate)
    assert not observe(gate, packet(**({"sequence": 2, "observed_at": 1001} | changes)),
                       wall=1001, mono=101)
    assert gate.current(101) is None


@pytest.mark.parametrize("payload", ["not json", "[]", "null", "{}", "x" * 4097])
def test_foreground_snapshot_malformed_payload_is_unknown(payload):
    gate = foreground_gate()
    assert observe(gate)
    assert not observe(gate, payload, wall=1001, mono=101)
    assert gate.current(101) is None


def test_foreground_snapshot_retired_epoch_cannot_retake_control():
    gate = foreground_gate()
    assert observe(gate)
    assert observe(gate, packet(epoch="b" * 32, observed_at=1001), wall=1001, mono=101)
    assert not observe(gate, packet(sequence=99, observed_at=1002), wall=1002, mono=102)
    assert gate.current(102) == "Roblox"


def test_foreground_snapshot_same_epoch_clock_regression_does_not_renew():
    gate = foreground_gate()
    assert observe(gate)
    assert not observe(gate, packet(sequence=2, observed_at=999), wall=1001, mono=101)
    assert gate.current(109) == "Roblox"
    assert gate.current(110) is None


def test_foreground_snapshot_future_skew_cannot_extend_lifetime():
    gate = foreground_gate()
    assert observe(gate, packet(observed_at=1002))
    assert gate.current(109.99) == "Roblox"
    assert gate.current(110) is None


@pytest.mark.parametrize("changes", [
    {"sequence": 1 << 63}, {"epoch": None}, {"active_game": []},
    {"gaming_active": []}, {"observed_at": 10 ** 300}, {"extra": 1},
])
def test_foreground_snapshot_strict_schema(changes):
    gate = foreground_gate()
    assert not observe(gate, packet(**changes))
    assert gate.current(100) is None


def test_foreground_snapshot_rejects_duplicate_fields_and_invalid_utf8():
    gate = foreground_gate()
    assert not observe(gate, packet()[:-1] + ', "sequence": 2}')
    assert not observe(gate, b"\xff")
    assert gate.current(100) is None


def test_foreground_snapshot_invalid_clocks_fail_closed():
    gate = foreground_gate()
    assert observe(gate)
    assert not observe(gate, packet(sequence=2), wall=float("nan"))
    assert gate.current(100) is None
    assert observe(gate, packet(sequence=2))
    assert not observe(gate, packet(sequence=3), mono=99)
    assert gate.current(100) is None


def test_foreground_snapshot_monotonic_regression_on_read_invalidates():
    gate = foreground_gate()
    assert observe(gate)
    assert gate.current(99) is None
    assert gate.current(100) is None


def test_foreground_snapshot_reserved_or_ambiguous_enrolled_names_rejected():
    from custom_components.hal_gaming_control.foreground_snapshot import ForegroundLiveness
    gate = ForegroundLiveness("pc1", {"idle", "unknown", "unavailable", "", "A | B"})
    for name in ("idle", "unknown", "unavailable", "", "A | B"):
        assert not observe(gate, packet(active_game=name))
    assert gate.current(100) is None
