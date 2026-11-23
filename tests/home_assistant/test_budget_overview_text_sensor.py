"""Native per-device Budget overview text sensor (issue #93 follow-up)."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.hal_gaming_control.sensor import (
    BudgetOverviewSensor, async_setup_entry,
)

TZ = ZoneInfo("Europe/Zagreb")


def at(day=23):
    return datetime(2026, 11, day, 12, 0, tzinfo=TZ)


def pc(**options):
    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry.data = {"name": "Lucija Desktop"}
    coordinator.options = {
        "enabled": True, "daily": 180, "weekly": 300,
        "weekend_bonus": 0, "bonus_date": "2026-11-23",
        "bonus_minutes": 30, **options,
    }
    coordinator.last_update_success = True
    coordinator.direct = False
    coordinator.data = {
        "ready": True, "totals": {"daily": 204 * 60 + 5,
                                  "weekly": 204 * 60 + 5},
        "coverage_incomplete": False,
    }
    return coordinator


def test_device_sensor_is_read_only_and_shows_both_budgets_without_yaml():
    c = pc()
    sensor = BudgetOverviewSensor(c)
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now",
               return_value=at()):
        assert sensor.native_value == (
            "Today: 5m 55s left · Week: 1h 35m 55s left")
        details = sensor.extra_state_attributes
    assert sensor.unique_id == "pc1_budget_overview"
    assert sensor.name == "Budget overview"
    assert sensor.device_info["identifiers"] == {
        ("mqtt", "smarthouse_gaming_pc1")}
    assert sensor.entity_category is None  # Visible in the device's Sensors card.
    assert len(sensor.native_value) < 255
    assert details["overview_text"].splitlines() == [
        "Daily base: 180 min",
        "Weekend bonus: +0 min",
        "Parent bonus: +30 min",
        "Screen idle bonus: +0 min",
        "Daily allowance: 210 min",
        "Played today: 3h 24m 5s",
        "Remaining today: 5m 55s",
        "Weekly allowance: 300 min",
        "Played this week: 3h 24m 5s",
        "Remaining this week: 1h 35m 55s",
    ]
    assert details["coverage_incomplete"] is False


def test_offline_must_show_unknown_not_fabricated_zero_or_remaining():
    c = pc()
    c.data = {"ready": False, "totals": {"daily": 0, "weekly": 0},
              "coverage_incomplete": True}
    sensor = BudgetOverviewSensor(c)
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now",
               return_value=at()):
        assert sensor.available is True
        assert sensor.native_value == "Budget data unavailable"
        details = sensor.extra_state_attributes["overview_text"]
    assert "Daily allowance: 210 min" in details
    assert "Played today: Unknown" in details
    assert "Remaining today: Unknown" in details
    assert "Remaining this week: Unknown" in details
    assert "Coverage incomplete" in details
    assert "Played today: 0m" not in details


@pytest.mark.parametrize("overrides,expected", [
    ({"enabled": False}, "Gaming rules disabled"),
    ({"unlimited": True}, "Unlimited gaming"),
    ({"daily": -1}, "Today: Unlimited · Week: 1h 35m 55s left"),
    ({"weekly": -1}, "Today: 5m 55s left · Week: Unlimited"),
])
def test_rules_and_unlimited_cannot_be_mistaken_for_remaining_time(
        overrides, expected):
    c = pc(**overrides)
    sensor = BudgetOverviewSensor(c)
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now",
               return_value=at()):
        assert sensor.native_value == expected
        assert "Played today: 3h 24m 5s" in (
            sensor.extra_state_attributes["overview_text"])


def test_local_midnight_and_weekend_bonus_update_without_reenrollment():
    c = pc(weekend_bonus=60, bonus_date="2026-11-22")
    c.data["totals"] = {"daily": 60 * 60, "weekly": 60 * 60}
    sensor = BudgetOverviewSensor(c)
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now",
               return_value=at(22)):
        sunday = sensor.extra_state_attributes["overview_text"]
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now",
               return_value=at(23)):
        monday = sensor.extra_state_attributes["overview_text"]
    assert "Weekend bonus: +60 min" in sunday
    assert "Parent bonus: +30 min" in sunday
    assert "Daily allowance: 270 min" in sunday
    assert "Weekend bonus: +0 min" in monday
    assert "Parent bonus: +0 min" in monday
    assert "Daily allowance: 180 min" in monday


@pytest.mark.asyncio
async def test_platform_registers_exactly_one_budget_overview_per_pc():
    coordinator = pc()
    entities = []
    await async_setup_entry(None, SimpleNamespace(runtime_data=coordinator),
                            lambda values: entities.extend(values))
    matches = [e for e in entities if isinstance(e, BudgetOverviewSensor)]
    assert len(matches) == 1
    assert matches[0].unique_id == "pc1_budget_overview"
    assert matches[0].entity_category is None
