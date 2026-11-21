"""Runtime regressions for discovery-off HA, with actual MQTT subscription callbacks."""
import json
from unittest.mock import AsyncMock, patch
import pytest

from homeassistant.components import mqtt
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.smarthouse_gaming.const import DOMAIN
from custom_components.smarthouse_gaming.direct_mqtt import direct_mode

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

# The MQTT mock itself leaves its periodic housekeeping timer (same fixture as the onboarding tests).
@pytest.fixture
def expected_lingering_timers():
    return True

DATA = {"device_id":"pc1","name":"Desktop Test","protocol_version":1,
        "games":["Roblox"],"actions":["terminate_game","lock_pc"]}
ROOT = "SmartHouse/Gaming/pc1"


async def test_direct_mode_setting(hass):
    entry = MockConfigEntry(domain="mqtt", data={"broker":"example.invalid"}, options={"discovery":False})
    entry.add_to_hass(hass)
    assert direct_mode(hass)
    hass.config_entries.async_update_entry(entry, options={"discovery":True})
    assert not direct_mode(hass)


async def test_scoped_entities_and_safe_controls(hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1", data=DATA)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = [registry.async_get_or_create(platform, DOMAIN, "pc1_"+key, config_entry=entry).entity_id
              for platform, key in [("sensor","played_daily"), ("sensor","remaining_weekly"),
                                    ("sensor","played_game_0123456789abcdef"),
                                    ("sensor","restriction"), ("binary_sensor","allowed")]]
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    keys = {"uptime":"sensor", "current_game":"sensor", "in_game":"binary_sensor",
            "terminate_game":"button", "lock_pc":"button"}
    ids = {key:registry.async_get_entity_id(platform, DOMAIN, "pc1_"+key) for key,platform in keys.items()}
    assert all(ids.values())
    assert all(registry.async_get(eid) is None for eid in legacy)
    owned = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {e.unique_id for e in owned if e.entity_id.split(".")[0] in ("sensor","binary_sensor")} == {"pc1_uptime","pc1_in_game","pc1_current_game","pc1_budget_daily","pc1_budget_weekly","pc1_agent_version","pc1_integration_version","pc1_active_game","pc1_gaming_active"}
    assert all(registry.async_get_entity_id(platform, "mqtt", "smarthouse_gaming_pc1_"+key) is None for key,platform in keys.items())
    assert len({registry.async_get(eid).device_id for eid in ids.values()}) == 1
    assert entry.runtime_data.entity_id("sensor","uptime") == ids["uptime"]
    assert entry.runtime_data.options["enabled"] is False
    assert registry.async_get_entity_id("switch",DOMAIN,"pc1_unlimited") is not None
    # Observe actual topic delivery. Nothing should publish on telemetry alone.
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        for suffix, payload in [("availability","online"),("state/uptime","100"),("state/in_game","ON"),("state/current_game","Roblox")]:
            async_fire_mqtt_message(hass, ROOT+"/"+suffix, payload)
        await hass.async_block_till_done()
        assert hass.states.get(ids["uptime"]).state == "100"
        assert hass.states.get(ids["current_game"]).state == "Roblox"
        assert hass.states.get(ids["in_game"]).state == "on"
        assert not publish.called
        await hass.services.async_call("button","press",{"entity_id":ids["lock_pc"]},blocking=True)
        publish.assert_awaited_once_with(hass,ROOT+"/command/lock_pc","PRESS",qos=0,retain=False)
        async_fire_mqtt_message(hass, ROOT+"/availability","offline")
        await hass.async_block_till_done()
        assert all(hass.states.get(eid).state == "unavailable" for eid in ids.values())
        assert publish.await_count == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_native_mode_no_duplicate_raw_entities(hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN,title=DATA["name"],unique_id="pc1",data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode",return_value=False):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor",DOMAIN,"pc1_uptime") is None
    assert registry.async_get_entity_id("button",DOMAIN,"pc1_lock_pc") is None
    assert registry.async_get_entity_id("sensor",DOMAIN,"pc1_budget_daily") is not None
    assert registry.async_get_entity_id("sensor",DOMAIN,"pc1_budget_weekly") is not None
    assert registry.async_get_entity_id("switch",DOMAIN,"pc1_unlimited") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_budget_entities_report_percent_and_keep_history_when_offline(hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1",
                            data=DATA, options={"enabled":True,"daily":60,"weekly":300})
    entry.add_to_hass(hass)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    daily = registry.async_get_entity_id("sensor",DOMAIN,"pc1_budget_daily")
    weekly = registry.async_get_entity_id("sensor",DOMAIN,"pc1_budget_weekly")
    c = entry.runtime_data
    with patch("custom_components.smarthouse_gaming.sensor.dt_util.now", return_value=__import__("datetime").datetime(2026,11,18,12)):
        c.async_set_updated_data({"ready":True,"online":False,"totals":{"daily":900,"weekly":3600}})
        assert float(hass.states.get(daily).state) == 75
        assert float(hass.states.get(weekly).state) == 80
        assert hass.states.get(daily).attributes["unit_of_measurement"] == "%"
        assert hass.states.get(weekly).attributes["unit_of_measurement"] == "%"
        c.async_set_updated_data({"ready":False,"online":False})
        assert hass.states.get(daily).state == "unavailable"
        assert hass.states.get(weekly).state == "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unlimited_switch_persists_without_reload_and_works_offline(hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1",
                            data=DATA, options={"enabled":True,"daily":60,"weekend_daily":120,
                                                "weekend_total":90,"unlimited":False})
    entry.add_to_hass(hass)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    c = entry.runtime_data
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id("switch",DOMAIN,"pc1_unlimited")
    assert hass.states.get(eid).state == "off"
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        for command, expected in [("turn_on",True), ("turn_off",False), ("turn_on",True)]:
            await hass.services.async_call("switch", command, {"entity_id":eid}, blocking=True)
            await hass.async_block_till_done()
            assert entry.runtime_data is c
            assert entry.options["unlimited"] is expected
            assert hass.states.get(eid).state == ("on" if expected else "off")
            assert c.options["daily"] == 60
            assert "weekend_total" not in c.options
        assert not publish.called
    assert await hass.config_entries.async_unload(entry.entry_id)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(eid).state == "on"
    assert entry.runtime_data.options["unlimited"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_live_budget_controls_and_action_configuration(hass, enable_custom_integrations, mqtt_mock):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from homeassistant.exceptions import HomeAssistantError
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1",
                            data=DATA, options={"enabled":True,"daily":60,"weekly":-1,"weekend_daily":120})
    entry.add_to_hass(hass)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    c = entry.runtime_data
    registry = er.async_get(hass)
    def entity(domain, key):
        return registry.async_get_entity_id(domain, DOMAIN, "pc1_"+key)
    daily = entity("number","daily_limit")
    weekly = entity("number","weekly_limit")
    weekend = entity("number","weekend_daily_limit")
    bonus = entity("button","add_daily_budget")
    assert all((daily, weekly, weekend, bonus))
    assert entity("select", "add_action") is None
    assert entity("select", "remove_action") is None
    state = hass.states.get(daily)
    assert float(state.state) == 60
    assert state.attributes["min"] == -10
    assert state.attributes["max"] == 600
    assert state.attributes["step"] == 10
    assert state.attributes["mode"] == "slider"
    assert float(hass.states.get(weekly).state) == -10
    assert entry.options["weekly"] == -1
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        for eid, value in [(daily,90),(weekly,300),(weekend,180)]:
            await hass.services.async_call("number","set_value",{"entity_id":eid,"value":value},blocking=True)
            await hass.async_block_till_done()
        assert entry.options["daily"] == 90
        assert entry.options["weekly"] == 300
        assert entry.options["weekend_daily"] == 180
        # All sliders must support returning to the original disabled sentinel.
        for eid, key in [(daily,"daily"),(weekly,"weekly"),(weekend,"weekend_daily")]:
            await hass.services.async_call("number","set_value",{"entity_id":eid,"value":-10},blocking=True)
            await hass.async_block_till_done()
            assert entry.options[key] == -1
            assert float(hass.states.get(eid).state) == -10
            await hass.services.async_call("number","set_value",{"entity_id":eid,"value":0},blocking=True)
            await hass.async_block_till_done()
            assert entry.options[key] == 0
            assert float(hass.states.get(eid).state) == 0
        for eid, value in [(daily,90),(weekly,300),(weekend,180)]:
            await hass.services.async_call("number","set_value",{"entity_id":eid,"value":value},blocking=True)
            await hass.async_block_till_done()
        now = datetime(2026,11,21,12,tzinfo=ZoneInfo("Europe/Zagreb"))
        with patch("custom_components.smarthouse_gaming.button.dt_util.now", return_value=now):
            for _ in range(2):
                await hass.services.async_call("button","press",{"entity_id":bonus},blocking=True)
                await hass.async_block_till_done()
            assert entry.options["bonus_minutes"] == 60
            assert entry.options["bonus_date"] == "2026-11-21"
            assert entry.options["weekend_daily"] == 180
        with patch("custom_components.smarthouse_gaming.button.dt_util.now", return_value=now.replace(day=22)):
            await hass.services.async_call("button","press",{"entity_id":bonus},blocking=True)
            await hass.async_block_till_done()
            assert entry.options["bonus_minutes"] == 30
        assert entry.runtime_data is c
        assert not publish.called
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("direct", [False, True])
async def test_agent_version_is_independent_of_update_capability_and_pc_availability(
        hass, enable_custom_integrations, mqtt_mock, direct):
    import json
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=direct):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id("sensor", DOMAIN, "pc1_agent_version")
    assert eid
    assert registry.async_get(eid).entity_category.value == "diagnostic"
    assert hass.states.get(eid).state == "unknown"

    def report(version, topic=ROOT+"/discovery", **extra):
        async_fire_mqtt_message(hass, topic, json.dumps(DATA | {
            "agent_version":version, "remote_update":False} | extra))

    report("0.1.1")
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "0.1.1"
    assert hass.states.get(eid).attributes["version_source"] == "last_reported"
    async_fire_mqtt_message(hass, ROOT+"/availability", "offline")
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "0.1.1"
    report("0.9.0", topic="SmartHouse/Gaming/pc2/discovery", device_id="pc2")
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "0.1.1"
    report("invalid")
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "unknown"
    report("0.2.0")
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "0.2.0"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("direct", [True, False])
async def test_foreground_entities_only_in_scoped_mode(hass, enable_custom_integrations, mqtt_mock, direct):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=direct):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    for platform, key in [("sensor", "active_game"), ("binary_sensor", "gaming_active")]:
        assert bool(registry.async_get_entity_id(platform, DOMAIN, "pc1_" + key)) is direct
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_scoped_foreground_pair_rejects_unknown_and_inconsistent_data(
        hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    game = registry.async_get_entity_id("sensor", DOMAIN, "pc1_active_game")
    active = registry.async_get_entity_id("binary_sensor", DOMAIN, "pc1_gaming_active")
    legacy = registry.async_get_entity_id("sensor", DOMAIN, "pc1_current_game")
    assert game and active and legacy

    async def emit(*messages):
        for suffix, payload in messages:
            async_fire_mqtt_message(hass, ROOT + "/" + suffix, payload)
        await hass.async_block_till_done()

    def expect(game_value, active_value):
        # Active game is fed by the coordinator's normalized value (issue #65), never by
        # the legacy v1 topics; only the still-legacy gaming_active pair is asserted here.
        assert hass.states.get(game).state == "unavailable"
        assert hass.states.get(active).state == active_value

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        await emit(("availability", "online"), ("state/current_game", "Roblox"),
                   ("state/in_game", "ON"), ("state/uptime", "100"))
        expect("unavailable", "unavailable")
        # Old process presence is never a substitute for missing foreground data.
        assert hass.states.get(legacy).state == "Roblox"
        await emit(("discovery", json.dumps(DATA | {"focus_protocol": 1})),
                   ("state/gaming_active", "ON"), ("state/active_game", "Roblox"))
        expect("unavailable", "unavailable")
        await emit(("state/focus_availability", "online"))
        expect("Roblox", "on")

        # A mismatched pair must not advertise a confirmed foreground state.
        await emit(("state/gaming_active", "OFF"))
        expect("unavailable", "unavailable")
        await emit(("state/active_game", "idle"))
        expect("idle", "off")
        await emit(("state/focus_availability", "offline"))
        expect("unavailable", "unavailable")
        await emit(("state/gaming_active", "UNKNOWN"), ("state/active_game", "unknown"))
        expect("unavailable", "unavailable")
        await emit(("state/gaming_active", "ON"), ("state/active_game", "Roblox"),
                   ("state/focus_availability", "online"))
        expect("Roblox", "on")
        await emit(("state/active_game", "Not enrolled"))
        expect("unavailable", "unavailable")
        await emit(("state/active_game", "Roblox"))
        expect("Roblox", "on")
        await emit(("discovery", "{malformed"))
        expect("unavailable", "unavailable")
        await emit(("discovery", json.dumps(DATA | {"focus_protocol": True})),
                   ("state/gaming_active", "ON"), ("state/active_game", "Roblox"),
                   ("state/focus_availability", "online"))
        expect("unavailable", "unavailable")
        await emit(("discovery", json.dumps(DATA | {"focus_protocol": 1})),
                   ("state/gaming_active", "ON"), ("state/active_game", "Roblox"),
                   ("state/focus_availability", "online"))
        expect("Roblox", "on")
        # A downgrade must invalidate the foreground pair even if retained topics remain.
        await emit(("discovery", json.dumps(DATA)))
        expect("unavailable", "unavailable")
        assert hass.states.get(legacy).state == "Roblox"
        publish.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_scoped_foreground_is_device_scoped_and_resets_on_disconnect(
        hass, enable_custom_integrations, mqtt_mock):
    entries = [MockConfigEntry(domain=DOMAIN, title="PC " + pc, unique_id=pc,
                               data={**DATA, "device_id": pc, "name": "PC " + pc})
               for pc in ("pc1", "pc2")]
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=True):
        for entry in entries:
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    ids = {pc: (registry.async_get_entity_id("sensor", DOMAIN, pc + "_active_game"),
                registry.async_get_entity_id("binary_sensor", DOMAIN, pc + "_gaming_active"))
           for pc in ("pc1", "pc2")}
    assert all(eid for pair in ids.values() for eid in pair)

    async def emit(pc, *messages):
        for suffix, payload in messages:
            async_fire_mqtt_message(hass, f"SmartHouse/Gaming/{pc}/{suffix}", payload)
        await hass.async_block_till_done()

    def states(pc):
        return tuple(hass.states.get(eid).state for eid in ids[pc])

    # Advertise the configured identity, avoiding an unrelated metadata-triggered reload.
    for pc, game, flag in [("pc1", "Roblox", "ON"), ("pc2", "idle", "OFF")]:
        await emit(pc, ("discovery", json.dumps(DATA | {"device_id": pc, "name": "PC " + pc, "focus_protocol": 1})),
                   ("availability", "online"), ("state/gaming_active", flag),
                   ("state/active_game", game), ("state/focus_availability", "online"))
    assert states("pc1") == ("unavailable", "on")
    assert states("pc2") == ("unavailable", "off")
    await emit("pc1", ("availability", "offline"))
    assert states("pc1") == ("unavailable", "unavailable")
    assert states("pc2") == ("unavailable", "off")
    await emit("pc1", ("availability", "online"), ("state/focus_availability", "online"))
    assert states("pc1") == ("unavailable", "unavailable")
    await emit("pc1", ("state/gaming_active", "OFF"), ("state/active_game", "idle"))
    assert states("pc1") == ("unavailable", "off")
    for entry in entries:
        assert await hass.config_entries.async_unload(entry.entry_id)
