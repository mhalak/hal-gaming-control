"""Issue #93: one device-scoped, authoritative gaming budget receipt."""
from datetime import datetime
from types import SimpleNamespace
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
    assert result["screen_idle_bonus_minutes"] is None
    assert result["screen_idle_bonus_status"] == "pending"
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
    assert attrs["screen_idle_bonus_minutes"] is None
    assert attrs["coverage_incomplete"] is True
    assert "daily_limit_minutes" not in BudgetSensor(
        coordinator, "weekly", "Weekly budget remaining").extra_state_attributes
