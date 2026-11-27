"""Issue #93: one device-scoped, authoritative gaming budget receipt."""
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from custom_components.hal_gaming_control.rule_engine import (
    budget_overview, effective_budget_limit, violations,
)
from custom_components.hal_gaming_control.sensor import BudgetSensor


TZ = ZoneInfo("Europe/Zagreb")


def at(day, hour=12):
    return datetime(2026, 11, day, hour, tzinfo=TZ)


def settings(**kw):
    return {"enabled": True, "daily": 180, "weekly": 300,
            "weekend_bonus": 0, **kw}


def test_parent_bonus_is_additive_and_recorded_gaming_time_is_unchanged():
    opts = settings(bonus_date="2026-11-23", bonus_minutes=30)
    totals = {"daily": 210 * 60, "weekly": 240 * 60, "per_game": {"Roblox": 210 * 60}}
    before = {"daily": totals["daily"], "weekly": totals["weekly"],
              "per_game": dict(totals["per_game"])}
    result = budget_overview(opts, totals, at(23), ready=True,
                             coverage_incomplete=False)
    assert result["base_daily_minutes"] == 180
    assert result["parent_bonus_minutes"] == 30
    assert result["weekend_bonus_minutes"] == 0
    assert result["screen_idle_bonus_minutes"] == 0
    assert result["screen_idle_bonus_status"] == "automatic"
    assert result["daily_limit_minutes"] == 210
    assert result["daily_used_minutes"] == 210
    assert result["daily_remaining_minutes"] == 0
    assert result["weekly_limit_minutes"] == 300
    assert result["weekly_used_minutes"] == 240
    assert result["weekly_remaining_minutes"] == 60
    assert result["coverage_incomplete"] is False
    assert totals == before
    assert effective_budget_limit(opts, at(23), "daily") == 210


def test_weekend_bonus_applies_only_on_weekend_and_today_parent_bonus_expires():
    opts = settings(weekend_bonus=60, bonus_date="2026-11-21", bonus_minutes=30)
    spent = {"daily": 200 * 60, "weekly": 220 * 60}
    sat = budget_overview(opts, spent, at(21), ready=True)
    sun = budget_overview(opts, spent, at(22), ready=True)
    mon = budget_overview(opts, spent, at(23), ready=True)
    assert (sat["weekend_bonus_minutes"], sat["parent_bonus_minutes"],
            sat["daily_limit_minutes"]) == (60, 30, 270)
    assert (sun["weekend_bonus_minutes"], sun["parent_bonus_minutes"],
            sun["daily_limit_minutes"]) == (60, 0, 240)
    assert (mon["weekend_bonus_minutes"], mon["parent_bonus_minutes"],
            mon["daily_limit_minutes"]) == (0, 0, 180)
    assert all(result["weekly_limit_minutes"] == 300
               for result in (sat, sun, mon))


def test_weekly_can_block_despite_available_daily_minutes():
    opts = settings(daily=60, weekly=30)
    spent = {"daily": 10 * 60, "weekly": 30 * 60, "per_game": {}}
    result = budget_overview(opts, spent, at(23), ready=True)
    assert result["daily_remaining_minutes"] == 50
    assert result["weekly_remaining_minutes"] == 0
    assert violations(opts, spent, at(23), []) == ["weekly"]


def test_unknown_usage_never_becomes_zero_even_with_a_configured_limit():
    opts = settings()
    for totals, ready in (({}, True), ({"daily": 0, "weekly": 0}, False)):
        result = budget_overview(opts, totals, at(23), ready=ready,
                                 coverage_incomplete=True)
        assert result["daily_used_minutes"] is None
        assert result["weekly_used_minutes"] is None
        assert result["daily_remaining_minutes"] is None
        assert result["weekly_remaining_minutes"] is None
        assert result["coverage_incomplete"] is True


def test_rules_disabled_and_unlimited_are_distinct_from_zero_remaining():
    values = [
        (settings(enabled=False), "disabled", None),
        (settings(unlimited=True), "unlimited", None),
        (settings(daily=-1), "unlimited", None),
        (settings(daily=0), "limited", 0),
    ]
    for opts, status, remaining in values:
        result = budget_overview(opts, {"daily": 60, "weekly": 120},
                                 at(23), ready=True)
        assert result["daily_budget_status"] == status
        assert result["daily_remaining_minutes"] == remaining
    result = budget_overview(settings(weekly=-1), {"daily": 0, "weekly": 0},
                             at(23), ready=True)
    assert result["weekly_budget_status"] == "unlimited"
    assert result["weekly_remaining_minutes"] is None


def test_budget_receipt_attaches_to_existing_daily_sensor_identity():
    coordinator = Mock()
    coordinator.device_id = "lucija"
    coordinator.entry.data = {"name": "Lucija"}
    coordinator.last_update_success = True
    coordinator.options = settings(bonus_date="2026-11-23", bonus_minutes=30)
    coordinator.data = {"ready": True, "coverage_incomplete": True,
                        "totals": {"daily": 210 * 60, "weekly": 250 * 60}}
    entity = BudgetSensor(coordinator, "daily", "Daily budget remaining")
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now",
               return_value=at(23)):
        attrs = entity.extra_state_attributes
    assert entity.unique_id == "lucija_daily_budget_remaining"
    assert attrs["budget_minutes"] == attrs["daily_limit_minutes"] == 210
    assert attrs["used_minutes"] == attrs["daily_used_minutes"] == 210
    assert attrs["parent_bonus_minutes"] == 30
    assert attrs["weekly_remaining_minutes"] == 50
    assert attrs["screen_idle_bonus_minutes"] == 0
    assert attrs["coverage_incomplete"] is True
    assert "daily_limit_minutes" not in BudgetSensor(
        coordinator, "weekly", "Weekly budget remaining").extra_state_attributes


def test_last_minute_is_visible_in_seconds_without_early_round_up():
    opts = settings(daily=60)
    for played, remaining in ((59 * 60 + 37, 23),
                               (59 * 60 + 59.99, 1),
                               (60 * 60, 0)):
        totals = {"daily": played, "weekly": played, "per_game": {}}
        receipt = budget_overview(opts, totals, at(23), ready=True)
        assert receipt["daily_remaining_seconds"] == remaining
        assert receipt["daily_used_minutes"] < 60 if played < 3600 else receipt["daily_used_minutes"] == 60
        assert ("daily" in violations(opts, totals, at(23), [])) is (played >= 3600)


def test_unknown_and_unlimited_countdown_seconds_remain_none():
    incomplete = budget_overview(settings(), {}, at(23), ready=False)
    assert incomplete["daily_remaining_seconds"] is None
    assert incomplete["weekly_remaining_seconds"] is None
    unlimited = budget_overview(settings(daily=-1, weekly=-1),
                                {"daily": 0, "weekly": 0}, at(23), ready=True)
    assert unlimited["daily_remaining_seconds"] is None
    assert unlimited["weekly_remaining_seconds"] is None


def test_unlimited_gaming_override_is_not_merely_an_unlimited_daily_quota():
    """The UI must distinguish bypassing all rules from disabling one quota."""
    totals = {"daily": 90 * 60, "weekly": 90 * 60,
              "per_game": {"Roblox": 90 * 60}}
    common = settings(daily=60, weekly=30, per_game={"Roblox": 15},
                      schedule_enabled=True, schedule_start="16:00",
                      schedule_end="20:00")

    overridden = common | {"unlimited": True}
    active = budget_overview(overridden, totals, at(23), ready=True)
    assert active["unlimited_gaming_active"] is True
    assert active["daily_budget_status"] == "unlimited"
    assert active["weekly_budget_status"] == "unlimited"
    assert violations(overridden, totals, at(23), ["Roblox"]) == []
    assert active["daily_used_seconds"] == 90 * 60
    assert active["weekly_used_seconds"] == 90 * 60

    no_daily_quota = common | {"daily": -1, "unlimited": False}
    limited = budget_overview(no_daily_quota, totals, at(23), ready=True)
    assert limited["unlimited_gaming_active"] is False
    assert limited["daily_budget_status"] == "unlimited"
    assert limited["weekly_budget_status"] == "limited"
    assert limited["weekly_remaining_seconds"] == 0
    assert "weekly" in violations(no_daily_quota, totals, at(23), ["Roblox"])
    assert "schedule" in violations(no_daily_quota, totals, at(23), ["Roblox"])
    assert "game:Roblox" in violations(no_daily_quota, totals, at(23), ["Roblox"])

    ordinary = budget_overview(common, totals, at(23), ready=True)
    assert ordinary["unlimited_gaming_active"] is False
    assert ordinary["daily_budget_status"] == "limited"


def test_effective_time_sensor_uses_schedule_and_exact_seconds():
    from custom_components.hal_gaming_control.sensor import EffectiveBudgetSensor
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    from custom_components.hal_gaming_control.const import DEFAULTS
    now = at(23, 21).replace(minute=45)
    c = Mock(device_id="pc1", last_update_success=True)
    c.entry.data = {"name": "PC"}
    c.options = DEFAULTS | settings(daily=120, weekly=300, schedule_enabled=True,
                                    schedule_start="16:00", schedule_end="22:00")
    totals = {"daily": 3600, "weekly": 3600}
    c.data = {"ready": True, "totals": totals}
    sensor = EffectiveBudgetSensor(c)
    assert sensor.unique_id == "pc1_gaming_budget_remaining"
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now", return_value=now):
        assert sensor.native_value == 15
        attrs = sensor.extra_state_attributes
        assert attrs["remaining_seconds"] == 900
        assert attrs["limiting_budget"] == "schedule"
        assert attrs["effective_budget_minutes"] == 75
        assert attrs["remaining_percent"] == 20
        state = effective_snapshot(c.options, totals, now, "pc1", ready=True)
        c.options = prepare_grant(c.options, "pc1", now, 30, state.base_balances, c.options)
        assert sensor.native_value == 45
        assert sensor.extra_state_attributes["remaining_seconds"] == 2700
        assert sensor.extra_state_attributes["effective_budget_minutes"] == 105
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now",
               return_value=now.replace(hour=22, minute=30)):
        assert sensor.native_value == 0
        assert sensor.extra_state_attributes["remaining_percent"] == 0


def test_effective_time_sensor_unknown_unlimited_zero_and_weekly():
    from custom_components.hal_gaming_control.sensor import EffectiveBudgetSensor
    c = Mock(device_id="pc1", last_update_success=True)
    c.entry.data = {"name": "PC"}
    c.options = settings(daily=180, weekly=60)
    c.data = {"ready": True, "totals": {"daily": 0, "weekly": 3599.75}}
    sensor = EffectiveBudgetSensor(c)
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now", return_value=at(23)):
        assert sensor.native_value > 0
        assert sensor.extra_state_attributes["remaining_seconds"] == 0.25
        assert sensor.extra_state_attributes["limiting_budget"] == "weekly"
        assert sensor.extra_state_attributes["effective_budget_minutes"] == 60
        c.data["totals"]["weekly"] = 3600
        assert sensor.native_value == 0
        c.data["ready"] = False
        assert sensor.native_value is None
        assert sensor.extra_state_attributes["budget_status"] == "unknown"
        c.options["unlimited"] = True
        assert sensor.native_value is None
        assert sensor.extra_state_attributes["budget_status"] == "unlimited"
        c.options["enabled"] = False
        assert sensor.extra_state_attributes["budget_status"] == "disabled"


def test_gaming_penalty_deducts_effective_balance_without_mutating_usage():
    from custom_components.hal_gaming_control.gaming_penalty import add_penalty, undo_penalty, active_penalties
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    opts = settings(daily=220, weekly=600)
    now = at(23)
    totals = {"daily": 120 * 60, "weekly": 120 * 60, "per_game": {}}
    candidate = add_penalty(opts, "pc1", now, minutes=60, remaining_seconds=6000)
    snap = effective_snapshot(candidate, totals, now, "pc1", ready=True)
    assert snap.selection.remaining_seconds == 2400
    assert totals["daily"] == 7200 and candidate["daily"] == 220
    assert effective_snapshot(candidate, totals, now, "pc2", ready=True).selection.remaining_seconds == 6000
    assert effective_snapshot(candidate, totals, at(24), "pc1", ready=True).selection.remaining_seconds == 6000
    row = active_penalties(candidate, "pc1", now)[0]
    restored = undo_penalty(candidate, "pc1", now, row["id"])
    assert effective_snapshot(restored, totals, now, "pc1", ready=True).selection.remaining_seconds == 6000


def test_gaming_penalty_weekly_schedule_and_cancel_unlimited():
    from custom_components.hal_gaming_control.gaming_penalty import add_penalty
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    now = at(23, 18)
    totals = {"daily": 0, "weekly": 0, "per_game": {}}
    for opts in (settings(daily=180, weekly=10),
                 settings(daily=180, weekly=300, schedule_enabled=True,
                          schedule_start="16:00", schedule_end="18:10")):
        candidate = add_penalty(opts, "pc1", now, minutes=30, remaining_seconds=600)
        snap = effective_snapshot(candidate, totals, now, "pc1", ready=True)
        assert snap.selection.remaining_seconds == 0
        assert "penalty" in violations(candidate, totals, now, [], device_id="pc1")
        assert candidate["weekly"] == opts["weekly"]
    unlimited = settings(daily=-1, weekly=-1)
    cancelled = add_penalty(unlimited, "pc1", now, cancel_today=True)
    assert effective_snapshot(cancelled, totals, now, "pc1", ready=True).selection.remaining_seconds == 0
    assert violations(cancelled, totals, now, [], device_id="pc1") == ["penalty"]
    assert effective_snapshot(cancelled | {"unlimited": True}, totals, now, "pc1", ready=True).selection.status == "unlimited"
    assert effective_snapshot(cancelled, totals, at(24), "pc1", ready=True).selection.status == "unlimited"
    assert effective_snapshot(cancelled, {}, now, "pc1", ready=False).selection.status == "unknown"


def test_gaming_penalty_duplicate_cancel_and_invalid_amounts():
    import pytest
    from custom_components.hal_gaming_control.gaming_penalty import add_penalty, active_penalties, undo_penalty
    now = at(23)
    candidate = add_penalty(settings(), "pc1", now, cancel_today=True)
    assert add_penalty(candidate, "pc1", now, cancel_today=True) == candidate
    row = active_penalties(candidate, "pc1", now)[0]
    with pytest.raises(ValueError):
        undo_penalty(candidate, "pc2", now, row["id"])
    for value in (0, -1, True, 601, 1.5):
        with pytest.raises(ValueError):
            add_penalty(settings(), "pc1", now, minutes=value, remaining_seconds=3600)
    assert add_penalty(settings(), "pc1", now, minutes=30, remaining_seconds=0) == settings()


def test_penalty_receipt_undo_rows_and_balanced_total():
    from custom_components.hal_gaming_control.budget_select import budget_select_rows
    from custom_components.hal_gaming_control.gaming_penalty import add_penalty
    now = at(23)
    opts = add_penalty(settings(daily=220, weekly=600), "pc1", now,
                       minutes=60, remaining_seconds=6000)
    rows = budget_select_rows(opts, "pc1", {
        "ready": True, "totals": {"daily": 7200, "weekly": 7200, "per_game": {}}
    }, now)
    assert any("60 min - Gaming Penalty" in label and key.startswith("penalty:")
               for label, key in rows if key)
    assert "160 min - TOTAL" in rows[-3][0]
    assert "120 min - Gaming Session" in rows[-2][0]
    assert "40 min - Remaining Budget" in rows[-1][0]


def test_persistent_gaming_suspension_overrides_all_policy_and_survives_rollover():
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    from custom_components.hal_gaming_control.budget_select import budget_select_rows
    opts = settings(daily=-1, weekly=-1, enabled=False, unlimited=True, gaming_suspended=True)
    totals = {"daily": 600, "weekly": 1200, "per_game": {}}
    for now in (at(23), at(24), at(30)):
        snap = effective_snapshot(opts, totals, now, "pc1", ready=True)
        assert snap.selection.remaining_seconds == 0
        assert snap.selection.limiting_sources == ("suspended",)
        assert violations(opts, totals, now, [], device_id="pc1") == ["suspended"]
        rows = budget_select_rows(opts, "pc1", {"ready": True, "totals": totals}, now)
        assert "Gaming suspended" in rows[-3][0]
        assert "10 min - Gaming Session" in rows[-2][0]
        assert "0 min - Remaining Budget" in rows[-1][0]
    assert effective_snapshot(opts, {}, at(23), "pc1", ready=False).selection.status == "unknown"
    restored = opts | {"gaming_suspended": False, "unlimited": False, "enabled": True}
    assert effective_snapshot(restored, totals, at(24), "pc1", ready=True).selection.status == "unlimited"


def test_persistent_suspension_rejects_bonus():
    import pytest
    from custom_components.hal_gaming_control.smart_parent_control import prepare_live_grant
    with pytest.raises(ValueError, match="suspend"):
        prepare_live_grant(settings(gaming_suspended=True), "pc1", at(23), 30,
                           {"daily": 0, "weekly": 0, "per_game": {}}, ready=True)
