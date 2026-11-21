"""Owner-facing HA Active game and measured day/week sensor contract."""
from unittest.mock import Mock

from custom_components.smarthouse_gaming.sensor import (
    ActiveGameSensor, GamingTimeSensor,
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
    assert day.native_value == 2
    assert week.native_value == 4
    assert day.extra_state_attributes["coverage_incomplete"] is True
    assert day.extra_state_attributes["cutover_since"] == 100
    assert day.unique_id == "pc1_gaming_time_daily"


def test_previous_confirmed_history_remains_readable_when_offline():
    c = coordinator(ready=False, recorded=60, segments=True)
    sensor = GamingTimeSensor(c, "daily", "Daily gaming time")
    assert sensor.available is True
    assert sensor.native_value == 1
    c.foreground.export_segments.return_value = []
    assert sensor.available is False


def test_unknown_first_start_does_not_display_a_false_zero():
    c = coordinator(ready=False, recorded=0, segments=False)
    sensor = GamingTimeSensor(c, "daily", "Daily gaming time")
    assert sensor.available is False
