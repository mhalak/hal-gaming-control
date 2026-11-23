"""Owner-facing HA Active game and measured day/week sensor contract."""
from unittest.mock import Mock, patch

from custom_components.hal_gaming_control.sensor import (
    ActiveGameSensor, GamingTimeSensor, GamingTimeDisplaySensor, BudgetSensor,
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



def test_active_game_shows_validated_game_across_screen_off_with_dynamic_icons():
    c = coordinator(ready=True, name="idle")
    c.data.update(observed_game="Roblox", display_details={"state": "off"})
    sensor = ActiveGameSensor(c)

    # This is an observation, not the accounting state: quota/active_game is idle.
    assert c.data["active_game"] == "idle"
    assert sensor.native_value == "Roblox"
    assert sensor.icon == "mdi:monitor-off"
    assert sensor.extra_state_attributes["display_state"] == "off"

    c.data["display_details"]["state"] = "on"
    assert sensor.native_value == "Roblox"
    assert sensor.icon == "mdi:monitor"
    c.data["observed_game"] = "idle"
    assert sensor.native_value == "idle"
    assert sensor.icon == "mdi:monitor"

    # A rejected OFF is UNKNOWN, never misleadingly shown as monitor OFF.
    c.data["display_details"] = {"state": "unknown", "reported_state": "off"}
    assert sensor.icon == "mdi:gamepad-variant"
    assert sensor.extra_state_attributes["display_reported_state"] == "off"
    c.data["observed_game"] = None
    assert sensor.native_value is None
    c.data["ready"] = False
    assert not sensor.available


def test_gaming_time_displays_verified_elapsed_with_incomplete_coverage():
    c = coordinator(ready=True)
    day = GamingTimeSensor(c, "daily", "Daily gaming time")
    week = GamingTimeSensor(c, "weekly", "Weekly gaming time")
    assert day.native_value == round(120 / 60, 6)
    assert week.native_value == round(240 / 60, 6)
    assert day.extra_state_attributes["coverage_incomplete"] is True
    assert day.extra_state_attributes["cutover_since"] == 100
    assert day.unique_id == "pc1_gaming_time_daily"
    assert day.native_unit_of_measurement == "min"
    assert week.native_unit_of_measurement == "min"


def test_previous_confirmed_history_remains_readable_when_offline():
    c = coordinator(ready=False, recorded=60, segments=True)
    sensor = GamingTimeSensor(c, "daily", "Daily gaming time")
    assert sensor.available is True
    assert sensor.native_value == round(60 / 60, 6)
    c.foreground.export_segments.return_value = []
    assert sensor.available is False


def test_unknown_first_start_does_not_display_a_false_zero():
    c = coordinator(ready=False, recorded=0, segments=False)
    sensor = GamingTimeSensor(c, "daily", "Daily gaming time")
    assert sensor.available is False


def test_long_duration_keeps_hours_minutes_and_seconds():
    from homeassistant.const import UnitOfTime
    c = coordinator(ready=True, recorded=711 * 60 + 3)
    pretty = GamingTimeDisplaySensor(c, "daily", "Daily gaming time")
    numeric = GamingTimeSensor(c, "daily", "Daily gaming time (minutes)")
    assert pretty.native_value == "11h 51m 3s"
    assert pretty.native_unit_of_measurement is None
    assert pretty.device_class is None
    assert pretty.unique_id == "pc1_gaming_time_display_daily"
    assert numeric.native_unit_of_measurement == UnitOfTime.MINUTES
    assert abs(numeric.native_value * 60 - (711 * 60 + 3)) < 0.001
    assert numeric.unique_id == "pc1_gaming_time_daily"


def test_formatted_time_zero_short_and_unavailable():
    c = coordinator(ready=True, recorded=0)
    day = GamingTimeDisplaySensor(c, "daily", "Daily gaming time")
    assert day.native_value == "0h 0m 0s"
    c.data["recorded_totals"]["daily"] = 63
    assert day.native_value == "0h 1m 3s"
    c.data["recorded_totals"]["daily"] = 3599.8
    assert day.native_value == "1h 0m 0s"
    c.data["recorded_totals"]["daily"] = None
    assert day.native_value is None
    c.data["recorded_totals"] = {}
    assert day.native_value is None
    c.data.pop("recorded_totals")
    assert not day.available
