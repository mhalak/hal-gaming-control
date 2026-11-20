"""Issue #4: confirmed foreground intervals; never count process presence."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from custom_components.smarthouse_gaming.foreground_accounting import ForegroundLedger

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
