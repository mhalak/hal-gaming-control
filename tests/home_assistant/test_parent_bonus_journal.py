"""Issue #165: stable, durable parent bonus grants and safe per-grant revocation."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from custom_components.hal_gaming_control.parent_bonus import (
    add_parent_grant, revoke_parent_grant, parent_bonus_total, parent_grants_today,
)
from custom_components.hal_gaming_control.rule_engine import effective_budget_limit

TZ = ZoneInfo("Europe/Zagreb")


def now(day=22, hour=14, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def test_three_grants_middle_cancel_is_idempotent_and_does_not_change_usage():
    opts = {"enabled": True, "daily": 180, "weekly": 300}
    for minute in (1, 2, 3):
        opts = add_parent_grant(opts, "pc1", now(minute=minute), 30)
    grants = parent_grants_today(opts, now())
    ids = [x["id"] for x in grants]
    assert len(ids) == len(set(ids)) == 3
    assert opts["bonus_minutes"] == parent_bonus_total(opts, now()) == 90
    assert effective_budget_limit(opts, now(), "daily") == 270
    assert effective_budget_limit(opts, now(), "weekly") == 300
    opts = revoke_parent_grant(opts, "pc1", ids[1], now(minute=5))
    assert opts["bonus_minutes"] == parent_bonus_total(opts, now()) == 60
    assert effective_budget_limit(opts, now(), "daily") == 240
    assert len(parent_grants_today(opts, now())) == 2
    cancelled = [e for e in opts["parent_bonus_journal"]["events"]
                 if e["id"] == ids[1]]
    assert cancelled[0]["status"] == "cancelled"
    assert cancelled[0]["cancelled_at_utc"] is not None
    with pytest.raises(ValueError, match="cancelled"):
        revoke_parent_grant(opts, "pc1", ids[1], now(minute=6))
    assert opts["bonus_minutes"] == 60
    assert "daily_used" not in opts


def test_legacy_bonus_is_unattributed_not_fake_historical_events():
    opts = {"daily": 180, "bonus_date": "2026-11-22", "bonus_minutes": 45}
    upgraded = add_parent_grant(opts, "pc1", now(), 30)
    assert upgraded["parent_bonus_journal"]["legacy"] == {
        "date": "2026-11-22", "minutes": 45,
    }
    assert len(upgraded["parent_bonus_journal"]["events"]) == 1
    assert parent_bonus_total(upgraded, now()) == 75
    assert upgraded["bonus_minutes"] == 75
    assert opts == {"daily": 180, "bonus_date": "2026-11-22", "bonus_minutes": 45}
    with pytest.raises(ValueError, match="Unknown"):
        revoke_parent_grant(upgraded, "pc1", "legacy", now())
    assert parent_bonus_total(upgraded, now(23)) == 0


def test_cross_device_and_expired_grants_must_not_revoke():
    opts = add_parent_grant({"daily": 120}, "pc1", now(), 30)
    grant_id = parent_grants_today(opts, now())[0]["id"]
    for dev, when, message in [("pc2", now(), "device"), ("pc1", now(23), "expired")]:
        with pytest.raises(ValueError, match=message):
            revoke_parent_grant(opts, dev, grant_id, when)
    assert parent_bonus_total(opts, now()) == 30


def test_persistent_json_and_local_day_rollover_preserve_audit():
    first = add_parent_grant({"daily": 100}, "pc1", now(), 30)
    second = add_parent_grant(json.loads(json.dumps(first)), "pc1", now(23), 30)
    assert second["bonus_date"] == "2026-11-23"
    assert second["bonus_minutes"] == parent_bonus_total(second, now(23)) == 30
    assert parent_bonus_total(second, now()) == 30
    assert len(second["parent_bonus_journal"]["events"]) == 2
    assert [e["local_date"] for e in second["parent_bonus_journal"]["events"]] == [
        "2026-11-22", "2026-11-23",
    ]


def test_unknown_or_broken_ledger_refuses_to_overwrite_audit():
    corrupt = {"daily": 120, "parent_bonus_journal": {"version": 99, "events": []}}
    with pytest.raises(ValueError, match="journal"):
        add_parent_grant(corrupt, "pc1", now(), 30)
    with pytest.raises(ValueError, match="journal"):
        parent_bonus_total(corrupt, now())


def test_bonus_event_time_is_utc_even_during_dst_overlap():
    # 02:30 occurs twice in Europe/Zagreb on fallback Sunday.
    first = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=0)
    second = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=1)
    opts = add_parent_grant({}, "pc1", first, 30)
    opts = add_parent_grant(opts, "pc1", second, 30)
    timestamps = [e["created_at_utc"]
                  for e in opts["parent_bonus_journal"]["events"]]
    assert timestamps[0] != timestamps[1]
    assert parent_bonus_total(opts, second) == 60


@pytest.mark.asyncio
async def test_add_30_button_produces_visible_distinct_entries_without_windows_commands():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock, patch
    from custom_components.hal_gaming_control.button import AddDailyBudget
    from custom_components.hal_gaming_control.const import DEFAULTS
    from custom_components.hal_gaming_control.rule_engine import budget_overview

    entry = SimpleNamespace(data={"device_id": "pc1", "name": "Test PC"},
                            options={"enabled": True, "daily": 180, "weekly": 300})
    c = Mock()
    c.device_id = "pc1"
    c.entry = entry
    c.last_update_success = True
    c.options = DEFAULTS | entry.options
    c.data = {"ready": True, "totals": {"daily": 0, "weekly": 0}}
    c.async_refresh = AsyncMock()

    def save(_entry, *, options):
        entry.options = options
        c.options = DEFAULTS | options

    add = AddDailyBudget(c)
    add.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=save))
    with patch("custom_components.hal_gaming_control.smart_parent_control.dt_util.now",
               return_value=now()):
        await add.async_press()
        await add.async_press()
    assert len(parent_grants_today(entry.options, now())) == 2
    receipt = budget_overview(c.options, {"daily": 0, "weekly": 0},
                              now(), ready=True, device_id="pc1")
    assert receipt["parent_bonus_minutes"] == 60
    assert len(receipt["parent_bonus_grants_today"]) == 2
    assert receipt["parent_bonus_recent_action"]["action"] == "added"
    assert receipt["parent_bonus_recent_action"]["minutes"] == 30
    assert receipt["parent_bonus_legacy_minutes"] == 0
    assert receipt["weekly_limit_minutes"] == 300
    assert "actions" not in entry.options



def test_budget_overview_recorder_attrs_bounded_and_cancel_receipt_is_latest():
    """30 grants should not persist two huge copies in Recorder attrs.

    A cancellation of an older grant is the last *action*, even if a newer
    grant still exists. Full journal and native select keep all active IDs.
    """
    from custom_components.hal_gaming_control.rule_engine import budget_overview
    opts = {"enabled": True, "daily": 120, "weekly": 300}
    for minute in range(1, 31):
        opts = add_parent_grant(opts, "pc1", now(minute=minute), 30)

    original = parent_grants_today(opts, now())
    assert len(original) == 30
    grant_id = original[15]["id"]
    opts = revoke_parent_grant(opts, "pc1", grant_id, now(minute=45))
    overview = budget_overview(
        opts, {"daily": 0, "weekly": 0}, now(minute=46), ready=True)
    assert len(overview["parent_bonus_grants_today"]) == 12
    assert len(overview["parent_bonus_activity_today"]) == 12
    assert overview["parent_bonus_recent_action"] == {
        "action": "cancelled",
        "minutes": 30,
        "at_utc": next(
            e["cancelled_at_utc"]
            for e in opts["parent_bonus_journal"]["events"]
            if e["id"] == grant_id
        ),
        "grant_id": grant_id,
    }
    assert len(opts["parent_bonus_journal"]["events"]) == 30
    assert len(parent_grants_today(opts, now())) == 29
    assert overview["parent_bonus_minutes"] == 29 * 30
    assert "daily_used" not in opts


@pytest.mark.asyncio
async def test_add_30_refuses_to_report_success_if_ha_rejects_save():
    """A failed write must never imply a new confirmed bonus."""
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.hal_gaming_control.button import AddDailyBudget
    from custom_components.hal_gaming_control.const import DEFAULTS

    old = {"enabled": True, "daily": 120, "weekly": 300}
    entry = SimpleNamespace(data={"device_id": "pc1", "name": "One PC"},
                            options=old.copy())
    coordinator = Mock(device_id="pc1", entry=entry, options=DEFAULTS | old)
    coordinator.data = {"ready": True, "totals": {"daily": 0, "weekly": 0}}
    coordinator.async_refresh = AsyncMock()
    button = AddDailyBudget(coordinator)
    def decline(*args, **kwargs):
        return False
    button.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=decline))
    with patch("custom_components.hal_gaming_control.smart_parent_control.dt_util.now",
               return_value=now()), pytest.raises(
                   HomeAssistantError, match="not saved"):
        await button.async_press()
    assert entry.options == old
    assert parent_bonus_total(entry.options, now()) == 0


@pytest.mark.asyncio
async def test_concurrent_parent_buttons_on_one_pc_preserve_both_grants():
    """Both explicit +30 presses must be recorded, not silently coalesced."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from custom_components.hal_gaming_control.button import AddDailyBudget
    from custom_components.hal_gaming_control.const import DEFAULTS

    opts = {"enabled": True, "daily": 120, "weekly": 300}
    entry = SimpleNamespace(data={"device_id": "pc1", "name": "One PC"},
                            options=opts)
    coordinator = Mock(device_id="pc1", entry=entry)
    coordinator.options = DEFAULTS | opts
    coordinator.data = {"ready": True, "totals": {"daily": 0, "weekly": 0}}
    coordinator.async_refresh = AsyncMock()
    def save(_entry, *, options):
        entry.options = options
        coordinator.options = DEFAULTS | options
        return True
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=save))
    parent_a = AddDailyBudget(coordinator)
    parent_b = AddDailyBudget(coordinator)
    parent_a.hass = parent_b.hass = hass
    with patch("custom_components.hal_gaming_control.smart_parent_control.dt_util.now",
               return_value=now()):
        await asyncio.gather(parent_a.async_press(), parent_b.async_press())
    grants = parent_grants_today(entry.options, now())
    assert len(grants) == 2
    assert len({grant["id"] for grant in grants}) == 2
    from custom_components.hal_gaming_control.parent_bonus import parent_smart_grants
    assert sum(x.daily_seconds for x in parent_smart_grants(entry.options, "pc1", now()).values()) == 3600
    assert effective_budget_limit(entry.options, now(), "weekly", device_id="pc1") == 300


def test_revoking_consumed_grant_rechecks_daily_policy_without_erasing_time():
    """Undo may activate a daily restriction; it must not mutate usage totals."""
    from custom_components.hal_gaming_control.rule_engine import violations
    options = {"enabled": True, "daily": 60, "weekly": 300,
               "unlimited": False, "schedule_enabled": False, "per_game": {}}
    options = add_parent_grant(options, "pc1", now(), 30)
    grant = parent_grants_today(options, now())[0]
    totals = {"daily": 75 * 60, "weekly": 75 * 60, "per_game": {}}
    assert violations(options, totals, now(), []) == []
    updated = revoke_parent_grant(options, "pc1", grant["id"], now(minute=2))
    assert violations(updated, totals, now(), []) == ["daily"]
    assert totals == {"daily": 75 * 60, "weekly": 75 * 60, "per_game": {}}
    assert effective_budget_limit(updated, now(), "weekly") == 300


from datetime import timezone


def test_smart_intent_roundtrip_and_snapshot_isolation():
    from custom_components.hal_gaming_control.smart_bonus_intent import capture_intent, read_intent
    at = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=1)
    balances = {'daily': -0.25, 'weekly': 1200}
    options = {'enabled': True, 'unlimited': False, 'schedule_enabled': True,
               'schedule_start': '20:00', 'schedule_end': '03:00', 'unrelated': 'secret'}
    record = capture_intent(at, balances, options)
    balances['daily'] = 99
    options['schedule_end'] = '23:00'
    restored = read_intent(json.loads(json.dumps(record)))
    assert restored.at.timestamp() == at.timestamp() and restored.at.fold == 1
    assert restored.at.date() == at.date()
    assert restored.base_balances == {'daily': -0.25, 'weekly': 1200}
    assert restored.schedule_options['schedule_end'] == '03:00'
    assert restored.schedule_options['weekend_schedule_end'] == '03:00'
    assert 'unrelated' not in record['schedule_options']
    restored.base_balances['daily'] = 0
    assert read_intent(record).base_balances['daily'] == -0.25


def test_smart_intent_no_schedule_and_utc():
    from custom_components.hal_gaming_control.smart_bonus_intent import capture_intent, read_intent
    at = datetime(2026, 11, 20, 21, tzinfo=timezone.utc)
    restored = read_intent(capture_intent(at, {'weekly': 0}))
    assert restored.at == at and restored.schedule_options is None
    assert restored.base_balances == {'weekly': 0}


@pytest.mark.parametrize('balance', [True, None, '1', float('inf'), float('nan')])
def test_smart_intent_invalid_balance(balance):
    from custom_components.hal_gaming_control.smart_bonus_intent import capture_intent
    with pytest.raises(ValueError):
        capture_intent(datetime(2026, 11, 20, tzinfo=TZ), {'daily': balance})


def test_smart_intent_rejects_corruption():
    from custom_components.hal_gaming_control.smart_bonus_intent import capture_intent, read_intent
    at = datetime(2026, 11, 20, tzinfo=TZ)
    record = capture_intent(at, {'daily': 0})
    for bad in [dict(record, version=True), dict(record, zone='Not/AZone'),
                dict(record, at_utc='2026-11-20T00:00:00'),
                dict(record, base_balances={'schedule': 0}), dict(record, schedule_options={})]:
        with pytest.raises(ValueError):
            read_intent(bad)
    with pytest.raises(ValueError):
        capture_intent(at.replace(tzinfo=None), {})


def transaction_at(day, hour=21, minute=45):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def transaction_schedule():
    return {"enabled": True, "unlimited": False, "schedule_enabled": True,
            "schedule_start": "16:00", "schedule_end": "22:00"}


def test_smart_transaction_replay_preserves_original_audit_after_restart():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant, cancel_grant
    from custom_components.hal_gaming_control.parent_bonus import parent_smart_grants
    first = prepare_grant({}, "pc1", transaction_at(19), 30, {"daily": 3600},
                          transaction_schedule())
    second = prepare_grant(first, "pc1", transaction_at(19, 22, 10), 30,
                           {"daily": 3600}, transaction_schedule())
    restored = json.loads(json.dumps(second))
    before = json.loads(json.dumps(restored))
    a, b = restored["parent_bonus_journal"]["events"]
    assert b["smart_adjustments"]["schedule_end_utc"] == "2026-11-19T22:00:00+00:00"
    updated = cancel_grant(restored, "pc1", a["id"], transaction_at(19, 22, 15))
    cancelled, surviving = updated["parent_bonus_journal"]["events"]
    assert cancelled["status"] == "cancelled"
    assert surviving["smart_original_adjustments"] == b["smart_adjustments"]
    assert surviving["smart_intent"] == b["smart_intent"]
    assert surviving["minutes"] == 30
    active = parent_smart_grants(updated, "pc1", transaction_at(19, 22, 15))
    assert list(active) == [b["id"]]
    assert active[b["id"]].schedule_end == transaction_at(19, 22, 40)
    assert restored == before
    assert first["parent_bonus_journal"]["events"][0]["status"] == "active"


def test_smart_transaction_weekly_replay_and_legacy():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant, cancel_grant
    from custom_components.hal_gaming_control.parent_bonus import parent_smart_grants
    original = add_parent_grant({"daily": 120, "weekly": 300}, "pc1", transaction_at(19), 15)
    first = prepare_grant(original, "pc1", transaction_at(19), 30, {"daily": 0, "weekly": 1200})
    second = prepare_grant(first, "pc1", transaction_at(19, 21, 46), 30,
                           {"daily": 0, "weekly": 1200})
    legacy, a, b = second["parent_bonus_journal"]["events"]
    assert b["smart_adjustments"]["weekly_seconds"] == 1800
    assert parent_bonus_total(second, transaction_at(19)) == 15
    updated = cancel_grant(second, "pc1", a["id"], transaction_at(19, 21, 47))
    assert updated["parent_bonus_journal"]["events"][0] == legacy
    assert updated["parent_bonus_journal"]["events"][2]["smart_adjustments"]["weekly_seconds"] == 600
    assert parent_smart_grants(updated, "pc1", transaction_at(20))[b["id"]].daily_seconds == 0
    assert parent_smart_grants(updated, "pc1", transaction_at(20))[b["id"]].weekly_seconds == 600
    assert parent_smart_grants(updated, "pc1", transaction_at(23)) == {}
    assert updated["daily"] == 120 and updated["weekly"] == 300


def test_smart_transaction_refuses_invalid_or_cross_device_cancel():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant, cancel_grant
    at = transaction_at(19)
    options = prepare_grant({}, "pc1", at, 30, {"weekly": 0})
    row = options["parent_bonus_journal"]["events"][0]
    for device, when, grant_id in [("pc2", at, row["id"]), ("pc1", transaction_at(20), row["id"]),
                                  ("pc1", at, "unknown")]:
        before = json.loads(json.dumps(options))
        with pytest.raises(ValueError):
            cancel_grant(options, device, grant_id, when)
        assert options == before
    broken = json.loads(json.dumps(options))
    broken["parent_bonus_journal"]["events"][0]["smart_intent"]["at_utc"] = "2026-11-18T12:00:00+00:00"
    with pytest.raises(ValueError):
        prepare_grant(broken, "pc1", at, 30, {"weekly": 0})
    with pytest.raises(ValueError):
        prepare_grant(options, "pc1", at, 30, {"weekly": None})


def test_smart_transaction_rejects_unreplayable_records_and_legacy_target():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant, cancel_grant
    from custom_components.hal_gaming_control.parent_bonus import add_smart_parent_grant
    at = transaction_at(19)
    incomplete = add_smart_parent_grant({}, "pc1", at, 30, {"weekly": 1800})
    with pytest.raises(ValueError, match="intent"):
        prepare_grant(incomplete, "pc1", at, 30, {"weekly": 0})
    legacy = add_parent_grant({}, "pc1", at, 30)
    with pytest.raises(ValueError, match="smart"):
        cancel_grant(legacy, "pc1", legacy["parent_bonus_journal"]["events"][0]["id"], at)


def test_smart_transaction_retains_history_and_device_isolation():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant
    old_at = datetime(2026, 10, 1, 14, tzinfo=TZ)
    old = prepare_grant({}, "pc1", old_at, 30, {"weekly": 0})
    other = prepare_grant(old, "pc2", transaction_at(19), 30, {"weekly": 0})
    latest = prepare_grant(other, "pc1", transaction_at(19), 30, {"weekly": 0})
    rows = latest["parent_bonus_journal"]["events"]
    assert len(rows) == 3
    assert rows[0] == old["parent_bonus_journal"]["events"][0]
    assert rows[1] == other["parent_bonus_journal"]["events"][1]
    assert rows[2]["smart_adjustments"]["weekly_seconds"] == 1800


def test_smart_transaction_prunes_expired_history_without_replaying_frozen_prefix():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant, cancel_grant
    from custom_components.hal_gaming_control.parent_bonus import parent_smart_grants
    old_at = datetime(2026, 5, 1, 14, tzinfo=TZ)
    old = prepare_grant({}, "pc1", old_at, 30, {"weekly": 0})
    first = prepare_grant(old, "pc1", transaction_at(18), 30, {"weekly": 0})
    assert len(first["parent_bonus_journal"]["events"]) == 1
    prefix = first["parent_bonus_journal"]["events"][0]
    second = prepare_grant(first, "pc1", transaction_at(19), 30, {"weekly": 0})
    third = prepare_grant(second, "pc1", transaction_at(19, 21, 46), 30, {"weekly": 0})
    rows = third["parent_bonus_journal"]["events"]
    assert rows[0] == prefix
    result = cancel_grant(third, "pc1", rows[1]["id"], transaction_at(19, 21, 47))
    assert result["parent_bonus_journal"]["events"][0] == prefix
    active = parent_smart_grants(result, "pc1", transaction_at(19, 21, 47))
    assert sum(row.weekly_seconds for row in active.values()) == 3600


def test_smart_transaction_preserves_old_schedule_interval_needed_by_current_replay():
    from datetime import timedelta
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant
    from custom_components.hal_gaming_control.parent_bonus import add_smart_parent_grant
    at = datetime(2026, 5, 1, 14, tzinfo=TZ)
    # A synthetic long historical extension tests retention independently of
    # how many ordinary grants would have been necessary to accumulate it.
    old = add_smart_parent_grant({}, "pc1", at, 30, {"schedule": 220 * 86400}, schedule_anchor=at)
    with pytest.raises(ValueError, match="intent"):
        prepare_grant(old, "pc1", transaction_at(19), 30, {"weekly": 0})


def test_live_smart_bonus_policy_before_after_schedule_and_unknown():
    from custom_components.hal_gaming_control.smart_parent_control import prepare_live_grant
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    opts = {"enabled": True, "daily": 180, "weekly": 300, "schedule_enabled": True,
            "schedule_start": "16:00", "schedule_end": "22:00"}
    totals = {"daily": 3600, "weekly": 3600}
    for stamp in (transaction_at(19, 15, 0),):
        with pytest.raises(ValueError, match="before"):
            prepare_live_grant(opts, "pc1", stamp, 30, totals, ready=True)
    stamp = transaction_at(19, 22, 20)
    updated = prepare_live_grant(opts, "pc1", stamp, 30, totals, ready=True)
    state = effective_snapshot(updated, totals, stamp, "pc1", ready=True)
    assert state.selection.remaining_seconds == 1800
    assert state.schedule.deadline == transaction_at(19, 22, 50)
    for policy, ready in [(opts, False), (opts | {"enabled": False}, True),
                          (opts | {"unlimited": True}, True)]:
        with pytest.raises(ValueError):
            prepare_live_grant(policy, "pc1", stamp, 30, totals, ready=ready)


def test_live_smart_bonus_weekly_only_and_minimal_adjustments():
    from custom_components.hal_gaming_control.smart_parent_control import prepare_live_grant
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    from custom_components.hal_gaming_control.parent_bonus import parent_smart_grants
    stamp = transaction_at(19, 16, 0)
    opts = {"enabled": True, "daily": -1, "weekly": 60}
    totals = {"daily": 0, "weekly": 3600}
    updated = prepare_live_grant(opts, "pc1", stamp, 30, totals, ready=True)
    state = effective_snapshot(updated, totals, stamp, "pc1", ready=True)
    assert state.selection.remaining_seconds == 1800
    adjustment = next(iter(parent_smart_grants(updated, "pc1", stamp).values()))
    assert adjustment.daily_seconds == 0 and adjustment.weekly_seconds == 1800
    assert updated["weekly"] == 60
