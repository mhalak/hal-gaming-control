"""Native budget controls: UI bounds, additive bonus and safe legacy migration."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming.const import DEFAULTS, DOMAIN
from custom_components.smarthouse_gaming.number import (
    CONTROLS,
    DISABLED_SLIDER_VALUE,
    GamingLimit,
)
from custom_components.smarthouse_gaming.rule_engine import effective_budget_limit


class StubCoordinator:
    """A minimal live options source, so setters exercise real entity logic."""

    def __init__(self, options=None, device_id="pc1"):
        self.entry = SimpleNamespace(
            data={"device_id": device_id, "name": "Test PC"},
            options=dict(options or {}),
        )
        self.device_id = device_id
        self.last_update_success = True
        self.data = {"ready": True}

    @property
    def options(self):
        return DEFAULTS | dict(self.entry.options)

    def async_add_listener(self, callback):
        return lambda: None


def control(key, options=None):
    coordinator = StubCoordinator(options)
    entity = GamingLimit(coordinator, key)
    saved = []

    def update(entry, *, options):
        saved.append(dict(options))
        entry.options = dict(options)

    entity.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=update)
    )
    return entity, coordinator, saved


@pytest.mark.parametrize("key,name,minimum,maximum,step,unique_id", [
    ("daily", "Daily budget", -10, 600, 10, "pc1_daily_limit"),
    ("weekly", "Weekly budget", 0, 4200, 60, "pc1_weekly_limit"),
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


def test_existing_daily_and_weekly_values_are_not_automatically_rewritten():
    daily, c, saved = control("daily", {"daily": -1, "weekly": 200})
    assert daily.native_value == DISABLED_SLIDER_VALUE
    weekly = GamingLimit(c, "weekly")
    assert weekly.native_value == 200  # old non-hour increment is preserved
    assert not saved
    c.entry.options["weekly"] = -1
    assert weekly.native_value is None  # no cap is never misrepresented as zero
    assert weekly.extra_state_attributes["requires_configuration"] is True
    c.entry.options["weekly"] = 5000
    assert weekly.native_value is None
    assert c.entry.options["weekly"] == 5000


@pytest.mark.asyncio
async def test_weekly_budget_rejects_10_minute_increments_but_accepts_hourly():
    weekly, c, saved = control("weekly", {"weekly": 300, "daily": 120})
    with patch.object(weekly, "async_write_ha_state"):
        await weekly.async_set_native_value(4200.0)
        assert saved[-1] == {"weekly": 4200, "daily": 120}
        await weekly.async_set_native_value(0)
        assert c.options["weekly"] == 0  # finite zero, not unlimited
        for invalid in (-60, -10, 10, 61, 4201, 4260, True, float("nan")):
            with pytest.raises(HomeAssistantError):
                await weekly.async_set_native_value(invalid)
    assert len(saved) == 2


@pytest.mark.asyncio
async def test_daily_disabled_semantics_and_bounds_are_preserved():
    daily, c, saved = control("daily", {"daily": 120})
    with patch.object(daily, "async_write_ha_state"):
        await daily.async_set_native_value(-10)
        assert saved[-1]["daily"] == -1
        await daily.async_set_native_value(600)
        await daily.async_set_native_value(0)
        assert c.options["daily"] == 0
        for invalid in (-20, 5, 610):
            with pytest.raises(HomeAssistantError):
                await daily.async_set_native_value(invalid)


@pytest.mark.asyncio
async def test_explicit_weekend_bonus_replaces_only_legacy_override():
    options = {"daily": 120, "weekly": 300, "weekend_daily": 220,
               "unlimited": False, "tracked_apps": [{"process": "roblox.exe", "name": "Roblox"}]}
    bonus, c, saved = control("weekend_bonus", options)
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Zagreb")
    saturday = datetime(2026, 11, 21, 12, tzinfo=tz)
    monday = datetime(2026, 11, 23, 12, tzinfo=tz)
    assert bonus.native_value == 100  # equivalent preview, NOT 220
    assert bonus.extra_state_attributes["mode"] == "legacy_override"
    assert effective_budget_limit(c.options, saturday, "daily") == 220
    assert "weekend_bonus" not in c.entry.options and not saved
    with patch.object(bonus, "async_write_ha_state"):
        await bonus.async_set_native_value(60)
    assert c.entry.options["weekend_bonus"] == 60
    assert "weekend_daily" not in c.entry.options
    assert c.entry.options["weekly"] == 300
    assert c.entry.options["tracked_apps"] == options["tracked_apps"]
    assert effective_budget_limit(c.options, saturday, "daily") == 180
    assert effective_budget_limit(c.options, monday, "daily") == 120
    assert effective_budget_limit(c.options, saturday, "weekly") == 300
    assert bonus.extra_state_attributes["mode"] == "additive_bonus"


@pytest.mark.asyncio
async def test_unrepresentable_legacy_override_needs_manual_choice():
    bonus, c, saved = control("weekend_bonus", {"daily": 300, "weekend_daily": 220})
    from datetime import datetime
    from zoneinfo import ZoneInfo

    saturday = datetime(2026, 11, 21, 12, tzinfo=ZoneInfo("Europe/Zagreb"))
    assert bonus.native_value is None
    assert bonus.extra_state_attributes["requires_manual_resolution"] is True
    assert effective_budget_limit(c.options, saturday, "daily") == 220
    assert not saved
    with patch.object(bonus, "async_write_ha_state"):
        await bonus.async_set_native_value(0)
    assert c.entry.options["weekend_bonus"] == 0
    assert effective_budget_limit(c.options, saturday, "daily") == 300


@pytest.mark.asyncio
async def test_only_obsolete_weekend_limit_entity_is_retired(hass):
    from homeassistant.helpers import entity_registry as er
    from custom_components.smarthouse_gaming import _remove_legacy_statistics

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_id": "pc1", "name": "Test PC"},
        options={"weekend_daily": 220, "weekly": 300},
        unique_id="pc1",
    )
    other = MockConfigEntry(
        domain=DOMAIN,
        data={"device_id": "pc2", "name": "Other PC"},
        options={},
        unique_id="pc2",
    )
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create("number", DOMAIN, "pc1_weekend_daily_limit", config_entry=entry)
    keep = registry.async_get_or_create("number", DOMAIN, "pc1_weekly_limit", config_entry=entry)
    other_old = registry.async_get_or_create("number", DOMAIN, "pc2_weekend_daily_limit", config_entry=other)
    _remove_legacy_statistics(hass, entry)
    assert registry.async_get(old.entity_id) is None
    assert registry.async_get(keep.entity_id) is not None
    assert registry.async_get(other_old.entity_id) is not None
    assert entry.options["weekend_daily"] == 220  # registry cleanup is not policy migration
