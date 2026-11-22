"""Native per-PC gaming schedule controls and passive restriction behavior."""
from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.components import mqtt
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parental_control.const import DEFAULTS, DOMAIN
from custom_components.parental_control.rule_engine import inside_schedule, violations
from custom_components.parental_control.time import GamingScheduleTime
from custom_components.parental_control.switch import ScheduleEnabledSwitch


# HA's mocked MQTT client owns a benign recurring housekeeping timer.
pytestmark = [pytest.mark.usefixtures("recorder_mock")]


@pytest.fixture
def expected_lingering_timers():
    return True


TZ = ZoneInfo("Europe/Zagreb")
DATA = {"device_id": "pc1", "name": "Test PC", "games": [],
        "actions": ["terminate_game", "lock_pc"], "protocol_version": 1}


def at(day, hour, minute=0, *, month=11, fold=0):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ, fold=fold)


class StubCoordinator:
    def __init__(self, options=None, device_id="pc1"):
        self.device_id = device_id
        self.entry = SimpleNamespace(data={"name": "Test PC"},
                                     options=dict(options or {}))
        self.last_update_success = True
        self.data = {"ready": False}

    @property
    def options(self):
        return DEFAULTS | self.entry.options

    def async_add_listener(self, callback):
        return lambda: None


def controls(options=None, device_id="pc1"):
    coordinator = StubCoordinator(options, device_id)
    updates = []

    def update_entry(entry, *, options):
        updates.append(dict(options))
        entry.options = dict(options)

    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=update_entry))
    start = GamingScheduleTime(coordinator, "schedule_start")
    end = GamingScheduleTime(coordinator, "schedule_end")
    toggle = ScheduleEnabledSwitch(coordinator)
    for entity in (start, end, toggle):
        entity.hass = hass
    return start, end, toggle, coordinator, updates


def test_schedule_controls_are_editable_on_device_even_when_pc_offline():
    start, end, toggle, _, updates = controls()
    assert (start.unique_id, end.unique_id, toggle.unique_id) == (
        "pc1_schedule_start", "pc1_schedule_end", "pc1_schedule_enabled")
    assert (start.name, end.name, toggle.name) == (
        "Weekday allowed from", "Weekday allowed until", "Schedule enabled")
    assert start.native_value == time(16)
    assert end.native_value == time(20)
    assert toggle.is_on is False
    assert start.entity_category == end.entity_category == toggle.entity_category == EntityCategory.CONFIG
    assert all(entity.available for entity in (start, end, toggle))
    assert updates == []  # Defaults must not write to HA.


@pytest.mark.asyncio
async def test_schedule_controls_preserve_all_existing_options_and_do_not_restart():
    existing = {"schedule_start": "17:15", "schedule_end": "21:30",
                "schedule_enabled": False, "daily": 120,
                "weekend_bonus": 50, "tracked_apps": [{"name": "Roblox"}]}
    start, end, toggle, c, updates = controls(existing)
    with patch.object(start, "async_write_ha_state"),          patch.object(end, "async_write_ha_state"),          patch.object(toggle, "async_write_ha_state"):
        assert start.native_value == time(17, 15)
        await start.async_set_value(time(18, 45))
        await end.async_set_value(time(2))
        await toggle.async_turn_on()
        await toggle.async_turn_on()  # no duplicate write
        assert c.options["schedule_start"] == "18:45"
        assert c.options["schedule_end"] == "02:00"
        assert c.options["schedule_enabled"] is True
        assert c.entry.options["tracked_apps"] == existing["tracked_apps"]
        assert c.entry.options["daily"] == 120
        assert c.entry.options["weekend_bonus"] == 50
        assert len(updates) == 3
        await toggle.async_turn_off()
        assert c.options["schedule_enabled"] is False
    assert len(updates) == 4
    assert start.native_value == time(18, 45) and end.native_value == time(2)


@pytest.mark.asyncio
async def test_schedule_validation_does_not_silently_truncate_seconds_or_timezone():
    start, _, _, c, updates = controls()
    with patch.object(start, "async_write_ha_state"):
        await start.async_set_value(time(22, 30, 15))
        assert c.options["schedule_start"] == "22:30:15"
        for invalid in ("22:00", None, 123, datetime(2026, 11, 22, 22),
                        time(22, tzinfo=TZ), time(22, 30, 1, 1)):
            with pytest.raises(HomeAssistantError):
                await start.async_set_value(invalid)
    assert len(updates) == 1


@pytest.mark.parametrize("start,end,now,expected", [
    ("16:00", "20:00", at(18, 16), True),
    ("16:00", "20:00", at(18, 19, 59), True),
    ("16:00", "20:00", at(18, 20), False),
    ("20:00", "02:00", at(18, 21), True),
    ("20:00", "02:00", at(19, 1, 59), True),
    ("20:00", "02:00", at(19, 2), False),
    ("20:00", "02:00", at(18, 12), False),
    ("16:00", "16:00", at(18, 3), True),
    ("20:00", "02:00", at(29, 1, month=3), True),
    ("20:00", "02:00", at(25, 1, month=10, fold=0), True),
    ("20:00", "02:00", at(25, 1, month=10, fold=1), True),
])
def test_allowed_window_boundaries_midnight_and_dst(start, end, now, expected):
    assert inside_schedule(now, start, end) is expected


def test_schedule_reason_only_when_both_switches_on_and_data_is_ready():
    totals = {"daily": 0, "weekly": 0, "per_game": {}}
    options = DEFAULTS | {"enabled": True, "schedule_enabled": True,
                          "schedule_start": "16:00", "schedule_end": "20:00"}
    assert violations(options, totals, at(18, 21), []) == ["schedule"]
    assert violations(options, totals, at(18, 18), []) == []
    assert violations(options | {"schedule_enabled": False}, totals, at(18, 21), []) == []
    assert violations(options | {"enabled": False}, totals, at(18, 21), []) == []
    assert violations(options | {"unlimited": True}, totals, at(18, 21), []) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [False, True])
async def test_schedule_entities_native_direct_mqtt_live_updates_and_reload(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="pc1", title="Test PC",
                            data=DATA, options={"enabled": True, "daily": 120,
                            "weekly": 4200, "schedule_start": "16:00",
                            "schedule_end": "20:00", "schedule_enabled": False,
                            "tracked_apps": []})
    entry.add_to_hass(hass)

    async def load():
        with patch("custom_components.parental_control.coordinator.direct_mode",
                   return_value=direct):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

    await load()
    reg = er.async_get(hass)
    start_id = reg.async_get_entity_id("time", DOMAIN, "pc1_schedule_start")
    end_id = reg.async_get_entity_id("time", DOMAIN, "pc1_schedule_end")
    toggle_id = reg.async_get_entity_id("switch", DOMAIN, "pc1_schedule_enabled")
    restriction_id = reg.async_get_entity_id("binary_sensor", DOMAIN,
                                              "pc1_gaming_restriction")
    assert all((start_id, end_id, toggle_id, restriction_id))
    assert hass.states.get(start_id).state == "16:00:00"
    assert hass.states.get(end_id).state == "20:00:00"
    assert hass.states.get(toggle_id).state == "off"
    c = entry.runtime_data

    def verified():
        c.async_set_updated_data({"ready": True, "online": True,
            "active_game": "idle", "active": [],
            "totals": {"daily": 0, "weekly": 0, "per_game": {}}})

    with patch("custom_components.parental_control.binary_sensor.dt_util.now",
               return_value=at(18, 21)),          patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        verified()
        await hass.async_block_till_done()
        assert hass.states.get(restriction_id).state == "off"
        await hass.services.async_call("switch", "turn_on",
                                       {"entity_id": toggle_id}, blocking=True)
        await hass.async_block_till_done()
        assert entry.runtime_data is c
        assert entry.options["schedule_enabled"] is True
        verified()
        await hass.async_block_till_done()
        assert hass.states.get(restriction_id).state == "on"
        assert hass.states.get(restriction_id).attributes["reason"] == "schedule"

        await hass.services.async_call("time", "set_value",
                {"entity_id": start_id, "time": "20:00:00"}, blocking=True)
        await hass.services.async_call("time", "set_value",
                {"entity_id": end_id, "time": "02:00:00"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.runtime_data is c
        assert entry.options["schedule_start"] == "20:00"
        assert entry.options["schedule_end"] == "02:00"
        verified()
        await hass.async_block_till_done()
        assert hass.states.get(restriction_id).state == "off"
        assert hass.states.get(start_id).state == "20:00:00"
        assert hass.states.get(end_id).state == "02:00:00"
        assert entry.options["daily"] == 120
        publish.assert_not_awaited()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await load()
    reg = er.async_get(hass)
    assert reg.async_get_entity_id("time", DOMAIN, "pc1_schedule_start") == start_id
    assert reg.async_get_entity_id("time", DOMAIN, "pc1_schedule_end") == end_id
    assert hass.states.get(toggle_id).state == "on"
    assert hass.states.get(start_id).state == "20:00:00"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_second_pc_schedule_cannot_modify_first():
    one, _, t1, c1, u1 = controls({"schedule_start": "16:00"}, "pc1")
    two, _, t2, c2, u2 = controls({"schedule_start": "10:00"}, "pc2")
    assert one.unique_id != two.unique_id and t1.unique_id != t2.unique_id
    with patch.object(two, "async_write_ha_state"), patch.object(t2, "async_write_ha_state"):
        await two.async_set_value(time(21, 5))
        await t2.async_turn_on()
    assert c1.options["schedule_start"] == "16:00" and c1.options["schedule_enabled"] is False
    assert c2.options["schedule_start"] == "21:05" and c2.options["schedule_enabled"] is True
    assert not u1 and len(u2) == 2
