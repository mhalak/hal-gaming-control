"""Weekend schedule: day-specific windows, rollover, HA controls and passive safety."""

from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components import mqtt
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hal_gaming_control.const import DEFAULTS, DOMAIN
from custom_components.hal_gaming_control.rule_engine import inside_weekly_schedule, violations
from custom_components.hal_gaming_control.time import GamingScheduleTime

pytestmark = [pytest.mark.usefixtures("recorder_mock")]


@pytest.fixture
def expected_lingering_timers():
    return True


TZ = ZoneInfo("Europe/Zagreb")
DATA = {"device_id": "pc1", "name": "Gaming PC", "games": [],
        "actions": ["lock_pc", "terminate_game"], "protocol_version": 1}


def at(day, hour, minute=0, *, month=11, fold=0):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ, fold=fold)


def schedule(**overrides):
    return DEFAULTS | {
        "enabled": True, "schedule_enabled": True, "daily": -1,
        "weekly": 4200, "schedule_start": "16:00", "schedule_end": "20:00",
        "weekend_schedule_start": "10:00", "weekend_schedule_end": "22:00",
    } | overrides


def test_weekday_and_weekend_controls_keep_unique_ids_and_config_category():
    class Coordinator:
        device_id = "pc1"
        last_update_success = True
        data = {"ready": False}
        entry = SimpleNamespace(data={"name": "Gaming PC"}, options={})
        options = DEFAULTS | {"schedule_start": "17:30", "schedule_end": "21:15"}
        def async_add_listener(self, callback):
            return lambda: None

    c = Coordinator()
    weekday = GamingScheduleTime(c, "schedule_start")
    weekday_end = GamingScheduleTime(c, "schedule_end")
    weekend = GamingScheduleTime(c, "weekend_schedule_start")
    weekend_end = GamingScheduleTime(c, "weekend_schedule_end")
    assert weekday.unique_id == "pc1_schedule_start"
    assert weekday_end.unique_id == "pc1_schedule_end"
    assert weekday.name == "Weekday allowed from"
    assert weekday_end.name == "Weekday allowed until"
    assert weekend.unique_id == "pc1_weekend_schedule_start"
    assert weekend_end.unique_id == "pc1_weekend_schedule_end"
    assert weekend.name == "Weekend allowed from"
    assert weekend_end.name == "Weekend allowed until"
    # Pre-upgrade entries with no weekend settings must not change permissions.
    assert weekend.native_value == time(17, 30)
    assert weekend_end.native_value == time(21, 15)
    assert all(x.entity_category == EntityCategory.CONFIG and x.available
               for x in (weekday, weekday_end, weekend, weekend_end))


def test_legacy_single_schedule_inherited_on_weekends_without_modifying_config():
    old = DEFAULTS | {"schedule_start": "18:00", "schedule_end": "22:30"}
    for day in (20, 21, 22, 23):  # Fri/Sat/Sun/Mon
        assert inside_weekly_schedule(at(day, 19), old)
        assert not inside_weekly_schedule(at(day, 23), old)
    assert "weekend_schedule_start" not in old
    assert "weekend_schedule_end" not in old
    assert not inside_weekly_schedule(at(21, 17), old)


@pytest.mark.parametrize("day,hour,expected", [
    (20, 12, False), (20, 16, True), (20, 19, True), (20, 20, False),
    (21, 9, False), (21, 10, True), (21, 21, True), (21, 22, False),
    (22, 10, True), (22, 21, True), (22, 22, False),
    (23, 10, False), (23, 16, True),
])
def test_local_weekday_weekend_windows(day, hour, expected):
    assert inside_weekly_schedule(at(day, hour), schedule()) is expected


def test_overnight_start_day_has_priority_across_weekend_boundaries():
    opts = schedule(schedule_start="20:00", schedule_end="02:00",
                    weekend_schedule_start="21:00", weekend_schedule_end="03:00")
    assert inside_weekly_schedule(at(20, 20), opts)
    assert inside_weekly_schedule(at(21, 1, 59), opts)  # Friday session
    assert not inside_weekly_schedule(at(21, 2), opts)
    assert not inside_weekly_schedule(at(21, 19), opts)
    assert inside_weekly_schedule(at(21, 21), opts)
    assert inside_weekly_schedule(at(22, 2, 59), opts)  # Saturday session
    assert not inside_weekly_schedule(at(22, 3), opts)
    assert inside_weekly_schedule(at(22, 22), opts)
    assert inside_weekly_schedule(at(23, 2, 59), opts)  # Sunday session
    assert not inside_weekly_schedule(at(23, 3), opts)
    assert not inside_weekly_schedule(at(23, 19), opts)


def test_overnight_does_not_allow_early_saturday_before_friday_session():
    opts = schedule(schedule_start="16:00", schedule_end="20:00",
                    weekend_schedule_start="20:00", weekend_schedule_end="03:00")
    assert not inside_weekly_schedule(at(21, 1), opts)
    assert inside_weekly_schedule(at(21, 20), opts)
    assert inside_weekly_schedule(at(22, 2, 59), opts)
    assert not inside_weekly_schedule(at(22, 3), opts)


def test_equal_times_mean_all_day_for_selected_start_day_only():
    opts = schedule(weekend_schedule_start="12:00", weekend_schedule_end="12:00",
                    schedule_start="16:00", schedule_end="20:00")
    assert inside_weekly_schedule(at(21, 0), opts)
    assert inside_weekly_schedule(at(22, 23), opts)
    assert not inside_weekly_schedule(at(23, 0), opts)


def test_previous_day_spillover_keeps_dst_local_clock_semantics():
    opts = schedule(schedule_start="20:00", schedule_end="02:30",
                    weekend_schedule_start="20:00", weekend_schedule_end="02:30")
    assert inside_weekly_schedule(at(29, 1, month=3), opts)  # spring morning
    assert inside_weekly_schedule(at(25, 2, month=10, fold=0), opts)
    assert inside_weekly_schedule(at(25, 2, month=10, fold=1), opts)
    assert not inside_weekly_schedule(at(25, 2, 30, month=10), opts)


def test_weekend_only_partial_override_inherits_unmodified_weekday_boundary():
    opts = schedule(weekend_schedule_start="10:00", weekend_schedule_end="22:00")
    opts.pop("weekend_schedule_end")
    assert inside_weekly_schedule(at(21, 19), opts)
    assert not inside_weekly_schedule(at(21, 20), opts)  # weekday end inherited


def test_weekend_restriction_reason_and_bypasses():
    totals = {"daily": 0, "weekly": 0, "per_game": {}}
    opts = schedule()
    assert violations(opts, totals, at(20, 12), []) == ["schedule"]
    assert violations(opts, totals, at(21, 12), []) == []
    assert violations(opts, totals, at(21, 23), []) == ["schedule"]
    assert violations(opts | {"schedule_enabled": False}, totals, at(21, 23), []) == []
    assert violations(opts | {"enabled": False}, totals, at(21, 23), []) == []
    assert violations(opts | {"unlimited": True}, totals, at(21, 23), []) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [False, True])
async def test_weekend_entity_runtime_changes_live_and_survives_reload(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1",
                            data=DATA, options={
                                "enabled": True, "schedule_enabled": True,
                                "schedule_start": "16:00", "schedule_end": "20:00",
                                "daily": 120, "weekly": 4200,
                                "tracked_apps": [{"process": "RobloxPlayerBeta.exe",
                                                 "signature": None, "name": "Roblox"}]})
    entry.add_to_hass(hass)

    async def load():
        with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
                   return_value=direct):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

    await load()
    reg = er.async_get(hass)
    weekday_id = reg.async_get_entity_id("time", DOMAIN, "pc1_schedule_start")
    weekend_from_id = reg.async_get_entity_id("time", DOMAIN, "pc1_weekend_schedule_start")
    weekend_until_id = reg.async_get_entity_id("time", DOMAIN, "pc1_weekend_schedule_end")
    restriction_id = reg.async_get_entity_id("binary_sensor", DOMAIN, "pc1_gaming_restriction")
    assert all([weekday_id, weekend_from_id, weekend_until_id, restriction_id])
    assert hass.states.get(weekend_from_id).state == "16:00:00"
    assert hass.states.get(weekend_until_id).state == "20:00:00"
    c = entry.runtime_data

    def refresh():
        c.async_set_updated_data({"ready": True, "online": True,
            "active_game": "idle", "active": [],
            "totals": {"daily": 0, "weekly": 0, "per_game": {}}})

    with patch("custom_components.hal_gaming_control.binary_sensor.dt_util.now",
               return_value=at(21, 12)), \
         patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        refresh()
        await hass.async_block_till_done()
        assert hass.states.get(restriction_id).state == "on"  # old weekday policy inherited
        await hass.services.async_call("time", "set_value",
              {"entity_id": weekend_from_id, "time": "10:00:00"}, blocking=True)
        await hass.services.async_call("time", "set_value",
              {"entity_id": weekend_until_id, "time": "22:00:00"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.runtime_data is c  # options update did not restart foreground
        assert entry.options["weekend_schedule_start"] == "10:00"
        assert entry.options["weekend_schedule_end"] == "22:00"
        assert entry.options["schedule_start"] == "16:00"
        assert entry.options["tracked_apps"][0]["name"] == "Roblox"
        refresh()
        await hass.async_block_till_done()
        assert hass.states.get(restriction_id).state == "off"
        publish.assert_not_awaited()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await load()
    assert er.async_get(hass).async_get_entity_id(
        "time", DOMAIN, "pc1_weekend_schedule_start") == weekend_from_id
    assert hass.states.get(weekend_from_id).state == "10:00:00"
    assert hass.states.get(weekend_until_id).state == "22:00:00"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_weekend_options_are_device_scoped_and_writable_while_offline():
    entries = [SimpleNamespace(data={"name": f"PC {n}"},
                               options={"schedule_start": "16:00", "schedule_end": "20:00"})
               for n in (1, 2)]
    changes = []
    def coordinator(idx):
        c = SimpleNamespace(device_id=f"pc{idx + 1}", entry=entries[idx],
                            last_update_success=True, data={"ready": False})
        c.options = DEFAULTS | entries[idx].options
        c.async_add_listener = lambda callback: lambda: None
        return c
    first = GamingScheduleTime(coordinator(0), "weekend_schedule_start")
    second = GamingScheduleTime(coordinator(1), "weekend_schedule_start")

    def save(entry, *, options):
        changes.append(dict(options))
        entry.options = dict(options)
    second.hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=save))
    with patch.object(second, "async_write_ha_state"):
        await second.async_set_value(time(11, 30))
    assert first.unique_id != second.unique_id
    assert first.native_value == time(16)
    assert entries[0].options == {"schedule_start": "16:00", "schedule_end": "20:00"}
    assert entries[1].options["weekend_schedule_start"] == "11:30"
    assert len(changes) == 1
