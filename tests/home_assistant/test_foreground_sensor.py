"""Owner-facing HA Active game and measured day/week sensor contract."""
from unittest.mock import Mock, patch

from custom_components.smarthouse_gaming.sensor import (
    ActiveGameSensor, GamingTimeSensor, BudgetSensor,
)


def coordinator(*, ready, name=None, recorded=120, segments=True):
    c = Mock()
    c.device_id = "pc1"
    c.entry.data = {"name": "Gaming PC"}
    c.last_update_success = True
    c.data = {
        "ready": ready, "active_game": name,
        "recorded_totals": {"daily": recorded, "weekly": recorded * 2},
        "coverage_incomplete": True, "cutover_since": 100,
    }
    c.foreground.export_segments.return_value = (
        [(100, 120, "stable-app-key")] if segments else [])
    return c


def test_active_game_uses_only_coordinator_ha_name():
    c = coordinator(ready=True, name="Minecraft")
    obj = ActiveGameSensor(c)
    assert obj.unique_id == "pc1_active_game"
    assert obj.native_value == "Minecraft"
    assert obj.available
    c.data = {"ready": False, "active_game": None}
    assert obj.native_value is None
    assert not obj.available


def test_gaming_time_displays_verified_elapsed_with_incomplete_coverage():
    c = coordinator(ready=True)
    day = GamingTimeSensor(c, "daily", "Daily gaming time")
    week = GamingTimeSensor(c, "weekly", "Weekly gaming time")
    assert day.native_value == round(120 / 3600, 9)
    assert week.native_value == round(240 / 3600, 9)
    assert day.extra_state_attributes["coverage_incomplete"] is True
    assert day.extra_state_attributes["cutover_since"] == 100
    assert day.unique_id == "pc1_gaming_time_daily"
    assert day.native_unit_of_measurement == "h"
    assert week.native_unit_of_measurement == "h"


def test_previous_confirmed_history_remains_readable_when_offline():
    c = coordinator(ready=False, recorded=60, segments=True)
    sensor = GamingTimeSensor(c, "daily", "Daily gaming time")
    assert sensor.available is True
    assert sensor.native_value == round(60 / 3600, 9)
    c.foreground.export_segments.return_value = []
    assert sensor.available is False


def test_unknown_first_start_does_not_display_a_false_zero():
    c = coordinator(ready=False, recorded=0, segments=False)
    sensor = GamingTimeSensor(c, "daily", "Daily gaming time")
    assert sensor.available is False


def test_long_duration_keeps_hours_minutes_and_seconds():
    from homeassistant.const import UnitOfTime
    c = coordinator(ready=True, recorded=711 * 60 + 3)
    sensor = GamingTimeSensor(c, "daily", "Daily gaming time")
    assert sensor.native_unit_of_measurement == UnitOfTime.HOURS
    # Numeric duration with an hours unit lets HA's frontend format as H/M/S.
    assert abs(sensor.native_value * 3600 - (711 * 60 + 3)) < 0.001
    assert sensor.unique_id == "pc1_gaming_time_daily"


def test_budget_remaining_uses_clear_budget_and_parent_bonus_attribute_names():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    c = coordinator(ready=True, recorded=0)
    c.options = {"enabled": True, "daily": 120, "weekly": 420,
                 "weekend_bonus": 60, "bonus_date": "2026-11-21",
                 "bonus_minutes": 30}
    c.data["totals"] = {"daily": 0, "weekly": 0}
    saturday = datetime(2026, 11, 21, 12, tzinfo=ZoneInfo("Europe/Zagreb"))
    with patch("custom_components.smarthouse_gaming.sensor.dt_util.now", return_value=saturday):
        day = BudgetSensor(c, "daily", "Daily budget remaining")
        week = BudgetSensor(c, "weekly", "Weekly budget remaining")
        assert day.unique_id == "pc1_daily_budget_remaining"
        assert week.unique_id == "pc1_weekly_budget_remaining"
        assert day.extra_state_attributes["budget_minutes"] == 210
        assert day.extra_state_attributes["parent_bonus_minutes"] == 30
        assert week.extra_state_attributes["budget_minutes"] == 420
        assert "limit_minutes" not in day.extra_state_attributes
        assert "bonus_minutes" not in day.extra_state_attributes
