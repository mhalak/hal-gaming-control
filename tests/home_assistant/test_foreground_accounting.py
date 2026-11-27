"""Issue #4: confirmed foreground intervals; never count process presence."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from custom_components.hal_gaming_control.foreground_accounting import ForegroundLedger

UTC = timezone.utc
LOCAL = ZoneInfo("Europe/Zagreb")
EPOCH = "a" * 32
LATER = "b" * 32


def sample(ts, game="Roblox", active="ON", *, sequence=1, epoch=EPOCH, device="pc1"):
    return json.dumps({"version": 1, "device_id": device, "epoch": epoch,
                       "sequence": sequence, "observed_at": ts,
                       "active_game": game, "gaming_active": active})


def receive(ledger, ts, game="Roblox", active="ON", *, sequence=1,
            epoch=EPOCH, retained=False, device="pc1", delay=0):
    return ledger.observe(sample(ts, game, active, sequence=sequence,
                                 epoch=epoch, device=device),
                          retained=retained, wall_now=ts + delay,
                          monotonic_now=100000 + ts + delay)


def totals(ledger, now):
    return ledger.totals(datetime.fromtimestamp(now, UTC))


def test_only_consecutive_confirmed_foreground_game_is_charged():
    ledger = ForegroundLedger("pc1", ["Roblox", "Minecraft"])
    assert receive(ledger, 100, sequence=1)
    assert receive(ledger, 102, sequence=2)
    assert receive(ledger, 104, sequence=3)
    assert receive(ledger, 106, "idle", "OFF", sequence=4)
    assert totals(ledger, 108)["weekly"] == 4
    assert totals(ledger, 108)["per_game"]["Roblox"] == 4
    assert ledger.current(100108) == "idle"


def test_switching_games_never_double_counts_or_estimates_transition():
    ledger = ForegroundLedger("pc1", ["Roblox", "Minecraft"])
    assert receive(ledger, 100, sequence=1)
    assert receive(ledger, 102, sequence=2)
    assert receive(ledger, 104, "Minecraft", "ON", sequence=3)
    assert receive(ledger, 106, "Minecraft", "ON", sequence=4)
    assert totals(ledger, 108)["weekly"] == 4
    assert totals(ledger, 108)["per_game"] == {"Minecraft": 2, "Roblox": 2}


def test_browser_minimize_unknown_and_return_never_charge_unknown_gaps():
    ledger = ForegroundLedger("pc1", ["Roblox"])
    for i, (ts, game, active) in enumerate([
        (100, "Roblox", "ON"), (102, "Roblox", "ON"),
        (104, "idle", "OFF"), (106, "idle", "OFF"),
        (108, "unknown", "UNKNOWN"), (110, "Roblox", "ON"),
        (112, "Roblox", "ON"),
    ], 1):
        assert receive(ledger, ts, game, active, sequence=i)
    assert totals(ledger, 114)["weekly"] == 4


def test_nonretained_and_strictly_increasing_samples_are_required():
    ledger = ForegroundLedger("pc1", ["Roblox"])
    assert not receive(ledger, 100, sequence=1, retained=True)
    assert receive(ledger, 102, sequence=2)
    assert not receive(ledger, 104, sequence=2)
    assert not receive(ledger, 104, sequence=3, device="pc2")
    assert totals(ledger, 104)["weekly"] == 0
    assert receive(ledger, 106, sequence=4)
    assert totals(ledger, 108)["weekly"] == 0  # invalid packet broke continuity
    assert receive(ledger, 108, sequence=5)
    assert totals(ledger, 109)["weekly"] == 2


def test_gap_epoch_restart_and_downgrade_do_not_bridge_unknown_time():
    ledger = ForegroundLedger("pc1", ["Roblox"])
    assert receive(ledger, 100, sequence=1)
    assert receive(ledger, 102, sequence=2)
    assert receive(ledger, 150, sequence=3)
    assert receive(ledger, 152, sequence=4)
    assert receive(ledger, 154, sequence=1, epoch=LATER)
    assert receive(ledger, 156, sequence=2, epoch=LATER)
    ledger.invalidate()
    assert ledger.current(100156) is None
    assert receive(ledger, 160, sequence=3, epoch=LATER)
    assert receive(ledger, 162, sequence=4, epoch=LATER)
    assert totals(ledger, 164)["weekly"] == 8


def test_unenrolled_unknown_and_process_lists_cannot_be_counted():
    ledger = ForegroundLedger("pc1", ["Roblox"])
    assert receive(ledger, 100, sequence=1)
    assert not receive(ledger, 102, "Minecraft", "ON", sequence=2)
    assert not receive(ledger, 104, "Roblox | Minecraft", "ON", sequence=3)
    assert receive(ledger, 106, sequence=4)
    assert receive(ledger, 108, sequence=5)
    assert totals(ledger, 110)["weekly"] == 2
    assert ledger.current(100120) is None  # stale snapshot != confirmed idle


def test_weekly_daily_and_dst_windows_split_real_elapsed_seconds():
    ledger = ForegroundLedger("pc1", ["Roblox"])
    # Europe/Zagreb, midnight between Sunday and Monday. UTC samples are trusted.
    mon = datetime(2026, 11, 23, 0, 0, tzinfo=LOCAL).timestamp()
    assert receive(ledger, mon - 4, sequence=1)
    assert receive(ledger, mon - 2, sequence=2)
    assert receive(ledger, mon, sequence=3)
    assert receive(ledger, mon + 2, sequence=4)
    # 3 confirmed segments, 2 seconds each; latest Monday contains the last one.
    result = ledger.totals(datetime.fromtimestamp(mon + 4, LOCAL))
    assert result["daily"] == 2
    assert result["weekly"] == 2
    assert result["per_game"]["Roblox"] == 2


def test_persistent_restore_is_not_allowed_to_bridge_pre_restart_samples():
    ledger = ForegroundLedger("pc1", ["Roblox"])
    assert receive(ledger, 100, sequence=1)
    assert receive(ledger, 102, sequence=2)
    segments = ledger.export_segments()
    restored = ForegroundLedger("pc1", ["Roblox"], intervals=segments)
    assert receive(restored, 104, sequence=3)
    assert totals(restored, 104)["weekly"] == 2
    assert receive(restored, 106, sequence=4)
    assert totals(restored, 107)["weekly"] == 4


def test_missing_snapshots_are_not_replaced_with_legacy_process_presence():
    ledger = ForegroundLedger("pc1", ["Roblox"])
    assert ledger.totals(datetime.fromtimestamp(200, UTC))["weekly"] == 0
    assert ledger.current(100200) is None


def test_unlimited_bonus_credits_only_confirmed_play_and_keeps_raw_segments():
    from custom_components.hal_gaming_control.unlimited_bonus import (
        record_override, unlimited_credits)
    from datetime import timedelta

    start = datetime(2026, 11, 23, 12, tzinfo=LOCAL)
    end = start + timedelta(hours=5)
    stamp = start.timestamp()
    segments = ((stamp - 2400, stamp, "Roblox"),
                (stamp, stamp + 7200, "Roblox"),
                (stamp + 10800, stamp + 14400, "Minecraft"))
    options = record_override({}, "pc1", start, True)
    assert record_override(options, "pc1", start, True) == options
    provisional = unlimited_credits(options, "pc1", end, segments)
    assert provisional == {"daily": 10800, "weekly": 10800,
                           "per_game": {"Roblox": 7200, "Minecraft": 3600}}
    closed = record_override(options, "pc1", end, False)
    assert record_override(closed, "pc1", end, False) == closed
    assert unlimited_credits(closed, "pc1", end, segments) == provisional
    assert len(segments) == 3
    assert options["unlimited_bonus_journal"]["intervals"][-1][1] is None


def test_unlimited_bonus_local_rollover_and_restart_json_roundtrip():
    from custom_components.hal_gaming_control.unlimited_bonus import (
        record_override, unlimited_credits)
    from datetime import timedelta

    start = datetime(2026, 11, 22, 23, 50, tzinfo=LOCAL)
    end = start + timedelta(minutes=20)
    stamp = start.timestamp()
    options = record_override({}, "pc1", start, True)
    restored = json.loads(json.dumps(options))
    closed = record_override(restored, "pc1", end, False)
    segments = ((stamp, end.timestamp(), "Roblox"),)
    assert unlimited_credits(closed, "pc1", end, segments) == {
        "daily": 600, "weekly": 600, "per_game": {"Roblox": 600}}
    tomorrow = end + timedelta(days=1)
    assert unlimited_credits(closed, "pc1", tomorrow, segments) == {
        "daily": 0, "weekly": 600, "per_game": {}}


def test_unlimited_bonus_partial_overlap_gaps_and_multiple_sessions():
    from custom_components.hal_gaming_control.unlimited_bonus import (
        record_override, unlimited_credits)
    from datetime import timedelta

    start = datetime(2026, 11, 23, 12, tzinfo=LOCAL)
    at = lambda seconds: start + timedelta(seconds=seconds)
    stamp = start.timestamp()
    options = record_override({}, "pc1", at(10), True)
    options = record_override(options, "pc1", at(20), False)
    options = record_override(options, "pc1", at(30), True)
    segments = ((stamp, stamp + 15, "Roblox"),
                (stamp + 18, stamp + 35, "Minecraft"),
                (stamp + 40, stamp + 50, "Roblox"))
    assert unlimited_credits(options, "pc1", at(45), segments) == {
        "daily": 17, "weekly": 17, "per_game": {"Roblox": 10, "Minecraft": 7}}


def test_unlimited_bonus_rejects_foreign_corrupt_and_backward_records():
    import pytest
    from custom_components.hal_gaming_control.unlimited_bonus import (
        record_override, unlimited_credits)
    from datetime import timedelta

    start = datetime(2026, 11, 23, 12, tzinfo=LOCAL)
    options = record_override({}, "pc1", start, True)
    with pytest.raises(ValueError):
        unlimited_credits(options, "pc2", start, ())
    with pytest.raises(ValueError):
        record_override(options, "pc1", start - timedelta(seconds=1), False)
    corrupted = {"unlimited_bonus_journal": {
        "version": 1, "device_id": "pc1",
        "intervals": [[10, 30], [20, 40]]}}
    with pytest.raises(ValueError):
        unlimited_credits(corrupted, "pc1", start, ())
    assert unlimited_credits({}, "pc1", start, ()) == {
        "daily": 0, "weekly": 0, "per_game": {}}


def test_unlimited_bonus_dst_fall_back_uses_elapsed_seconds():
    from custom_components.hal_gaming_control.unlimited_bonus import (
        record_override, unlimited_credits)

    first = datetime(2026, 10, 25, 2, 15, tzinfo=LOCAL, fold=0)
    last = datetime(2026, 10, 25, 2, 15, tzinfo=LOCAL, fold=1)
    options = record_override({}, "pc1", first, True)
    options = record_override(options, "pc1", last, False)
    assert unlimited_credits(options, "pc1", last, (
        (first.timestamp(), last.timestamp(), "Roblox"),)) == {
        "daily": 3600, "weekly": 3600, "per_game": {"Roblox": 3600}}
