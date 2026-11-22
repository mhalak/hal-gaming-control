"""Native HA budget controls: new IDs, bounds, bonus and clean preview cutover."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parental import _remove_legacy_statistics
from custom_components.hal_gaming_control.const import DEFAULTS, DOMAIN
from custom_components.hal_gaming_control.number import (
    CONTROLS, DISABLED_SLIDER_VALUE, GamingBudget,
)
from custom_components.hal_gaming_control.rule_engine import effective_budget_limit


class StubCoordinator:
    def __init__(self, options=None):
        self.entry = SimpleNamespace(
            data={"device_id": "pc1", "name": "Test PC"},
            options=dict(options or {}),
        )
        self.device_id = "pc1"
        self.last_update_success = True
        self.data = {"ready": True}

    @property
    def options(self):
        # Old weekend fields are ignored by active policy.
        return DEFAULTS | {
            k: v for k, v in self.entry.options.items()
            if k not in {"weekend_daily", "weekend_total"}
        }

    def async_add_listener(self, callback):
        return lambda: None


def control(key, options=None):
    c = StubCoordinator(options)
    entity = GamingBudget(c, key)
    changes = []

    def update(entry, *, options):
        changes.append(dict(options))
        entry.options = dict(options)

    entity.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=update)
    )
    return entity, c, changes


@pytest.mark.parametrize("key,name,minimum,maximum,step,unique_id", [
    ("daily", "Daily budget", -10, 600, 10, "pc1_daily_budget"),
    ("weekly", "Weekly budget", 0, 4200, 60, "pc1_weekly_budget"),
    ("weekend_bonus", "Weekend bonus", 0, 600, 10, "pc1_weekend_bonus"),
])
def test_native_budget_metadata(key, name, minimum, maximum, step, unique_id):
    entity, _, _ = control(key)
    assert list(CONTROLS) == ["daily", "weekly", "weekend_bonus"]
    assert entity.name == name
    assert entity.unique_id == unique_id
    assert entity.native_min_value == minimum
    assert entity.native_max_value == maximum
    assert entity.native_step == step
    assert entity.available


def test_legacy_weekend_override_is_ignored_without_modifying_options():
    entity, c, changes = control("weekend_bonus",
                                 {"daily": 120, "weekend_daily": 220})
    saturday = datetime(2026, 11, 21, 12, tzinfo=ZoneInfo("Europe/Zagreb"))
    assert entity.native_value == 0
    assert entity.extra_state_attributes["configured_minutes"] == 0
    assert effective_budget_limit(c.options, saturday, "daily") == 120
    assert c.entry.options["weekend_daily"] == 220
    assert not changes


def test_weekly_old_unlimited_and_off_grid_values_never_become_zero():
    daily, c, changes = control("daily", {"daily": -1, "weekly": 200})
    assert daily.native_value == DISABLED_SLIDER_VALUE
    weekly = GamingBudget(c, "weekly")
    assert weekly.native_value == 200
    c.entry.options["weekly"] = -1
    assert weekly.native_value is None
    assert weekly.extra_state_attributes["requires_configuration"] is True
    c.entry.options["weekly"] = 5000
    assert weekly.native_value is None
    assert c.entry.options["weekly"] == 5000
    assert not changes


@pytest.mark.asyncio
async def test_weekly_budget_accepts_only_whole_hours_and_zero_is_finite():
    weekly, c, changes = control("weekly", {"weekly": 300, "daily": 120})
    with patch.object(weekly, "async_write_ha_state"):
        await weekly.async_set_native_value(4200.0)
        assert changes[-1] == {"weekly": 4200, "daily": 120}
        await weekly.async_set_native_value(0)
        assert c.options["weekly"] == 0
        for bad in (-60, -10, 10, 61, 4201, 4260, True, float("nan")):
            with pytest.raises(HomeAssistantError):
                await weekly.async_set_native_value(bad)
    assert len(changes) == 2


@pytest.mark.asyncio
async def test_daily_disabled_position_is_distinct_from_zero_budget():
    daily, c, changes = control("daily", {"daily": 120})
    with patch.object(daily, "async_write_ha_state"):
        await daily.async_set_native_value(-10)
        assert changes[-1]["daily"] == -1
        await daily.async_set_native_value(600)
        await daily.async_set_native_value(0)
        assert c.options["daily"] == 0
        for bad in (-20, 5, 610):
            with pytest.raises(HomeAssistantError):
                await daily.async_set_native_value(bad)


@pytest.mark.asyncio
async def test_weekend_bonus_is_explicit_additive_and_independent_of_weekly():
    options = {"daily": 120, "weekly": 300, "weekend_daily": 220,
               "unlimited": False, "tracked_apps": [
                   {"process": "roblox.exe", "name": "Roblox"}]}
    bonus, c, changes = control("weekend_bonus", options)
    sat = datetime(2026, 11, 21, 12, tzinfo=ZoneInfo("Europe/Zagreb"))
    mon = datetime(2026, 11, 23, 12, tzinfo=ZoneInfo("Europe/Zagreb"))
    assert bonus.native_value == 0
    with patch.object(bonus, "async_write_ha_state"):
        await bonus.async_set_native_value(60)
    assert changes[-1]["weekend_bonus"] == 60
    assert "weekend_daily" not in c.entry.options
    assert c.entry.options["weekly"] == 300
    assert c.entry.options["tracked_apps"] == options["tracked_apps"]
    assert effective_budget_limit(c.options, sat, "daily") == 180
    assert effective_budget_limit(c.options, mon, "daily") == 120
    assert effective_budget_limit(c.options, sat, "weekly") == 300


@pytest.mark.asyncio
async def test_retires_only_old_number_ids_on_correct_device(hass):
    from homeassistant.helpers import entity_registry as er
    entry = MockConfigEntry(
        domain=DOMAIN, data={"device_id": "pc1", "name": "Test PC"},
        unique_id="pc1")
    other = MockConfigEntry(
        domain=DOMAIN, data={"device_id": "pc2", "name": "Other PC"},
        unique_id="pc2")
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    old = [
        registry.async_get_or_create("number", DOMAIN, f"pc1_{key}", config_entry=entry)
        for key in ("daily_limit", "weekly_limit", "weekend_daily_limit")
    ]
    keep = registry.async_get_or_create("number", DOMAIN, "pc1_daily_budget",
                                        config_entry=entry)
    other_old = registry.async_get_or_create("number", DOMAIN, "pc2_weekly_limit",
                                             config_entry=other)
    _remove_legacy_statistics(hass, entry)
    assert all(registry.async_get(e.entity_id) is None for e in old)
    assert registry.async_get(keep.entity_id) is not None
    assert registry.async_get(other_old.entity_id) is not None


def test_fresh_weekly_budget_is_configurable_without_unknown_state():
    weekly, coordinator, updates = control("weekly")
    assert weekly.native_value == 4200
    assert weekly.native_min_value == 0
    assert weekly.native_step == 60
    assert coordinator.options["weekly"] == 4200
    assert not updates  # Reading a default never writes to HA config.
