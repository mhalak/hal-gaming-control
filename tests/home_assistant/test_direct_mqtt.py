"""Runtime regressions for discovery-off HA, with actual MQTT subscription callbacks."""
import json
from pathlib import Path
from time import time
from unittest.mock import AsyncMock, patch
import pytest

from homeassistant.components import mqtt
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.hal_gaming_control.const import DOMAIN
from custom_components.hal_gaming_control.direct_mqtt import direct_mode

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

# The MQTT mock itself leaves its periodic housekeeping timer (same fixture as the onboarding tests).
@pytest.fixture
def expected_lingering_timers():
    return True

DATA = {"device_id":"pc1","name":"Desktop Test","protocol_version":1,
        "games":["Roblox"],"actions":["terminate_game","lock_pc"]}
ROOT = "SmartHouse/Gaming/pc1"

V3_CONTRACT = (Path(__file__).resolve().parents[1] / "contracts" / "v3"
               / "telemetry-foreground.json")


def v3(device="pc1", seq=1, *, process="RobloxPlayerBeta.exe",
       state="foreground", epoch="a" * 32):
    """Use the same immutable MQTT v3 envelope as the Windows publisher tests."""
    packet = json.loads(V3_CONTRACT.read_text(encoding="utf-8"))
    packet.update(device_id=device, sequence=seq, epoch=epoch, observed_at=time())
    packet["foreground"].update(
        state=state, process=process if state == "foreground" else None,
        signature=None, sample_age_ms=0)
    packet["display"].update(
        state="unknown", event_epoch=None, event_sequence=None,
        event_age_ms=None, sample_age_ms=None)
    packet["system"].update(uptime_seconds=100, agent_version="0.4.0")
    raw = json.dumps(packet)
    from custom_components.hal_gaming_control.unified_telemetry import decode_telemetry
    assert decode_telemetry(raw, device, retained=False, wall_now=time())["version"] == 3
    return raw


def discovery_v3(device="pc1", games=None):
    return json.dumps(DATA | {"device_id": device, "name": "PC " + device,
                               "unified_telemetry_protocol": 3,
                               "games": [] if games is None else games})


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
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    keys = {"uptime":"sensor", "terminate_game":"button", "lock_pc":"button"}
    ids = {key:registry.async_get_entity_id(platform, DOMAIN, "pc1_"+key) for key,platform in keys.items()}
    assert all(ids.values())
    assert all(registry.async_get(eid) is None for eid in legacy)
    owned = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {e.unique_id for e in owned if e.entity_id.split(".")[0] in ("sensor","binary_sensor")} == {"pc1_uptime","pc1_daily_budget_remaining","pc1_weekly_budget_remaining","pc1_agent_version","pc1_integration_version","pc1_active_game","pc1_gaming_time_daily","pc1_gaming_time_weekly", "pc1_gaming_time_display_daily", "pc1_gaming_time_display_weekly", "pc1_gaming_restriction"}
    for old_key, old_domain in (("current_game", "sensor"), ("in_game", "binary_sensor"),
                                ("gaming_active", "binary_sensor")):
        assert registry.async_get_entity_id(old_domain, DOMAIN, "pc1_" + old_key) is None
    assert all(registry.async_get_entity_id(platform, "mqtt", "smarthouse_gaming_pc1_"+key) is None for key,platform in keys.items())
    assert len({registry.async_get(eid).device_id for eid in ids.values()}) == 1
    assert entry.runtime_data.entity_id("sensor","uptime") == ids["uptime"]
    assert entry.runtime_data.options["enabled"] is False
    assert registry.async_get_entity_id("switch",DOMAIN,"pc1_unlimited") is not None
    assert registry.async_get_entity_id("switch",DOMAIN,"pc1_gaming_rules_enabled") is not None
    # Observe actual topic delivery. Nothing should publish on telemetry alone.
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        for suffix, payload in [("availability", "online"), ("discovery", discovery_v3()),
                                ("state/telemetry", v3()),
                                ("state/uptime", "999999"), ("state/current_game", "Roblox")]:
            async_fire_mqtt_message(hass, ROOT+"/"+suffix, payload)
        await hass.async_block_till_done()
        assert entry.runtime_data.foreground.v3_capable is True
        assert entry.runtime_data.foreground.telemetry_order.received is not None
        assert hass.states.get(ids["uptime"]).state == "100"
        assert not publish.called
        await hass.services.async_call("button","press",{"entity_id":ids["lock_pc"]},blocking=True)
        publish.assert_awaited_once_with(hass,ROOT+"/command/lock_pc","PRESS",qos=0,retain=False)
        # An upgraded rules-free PC revokes terminate even if HA has the
        # previously registered button. No command may reach MQTT.
        async_fire_mqtt_message(hass, ROOT+"/discovery", json.dumps(DATA | {
            "games": [], "actions": ["lock_pc"]}))
        await hass.async_block_till_done()
        assert hass.states.get(ids["terminate_game"]).state == "unavailable"
        await hass.services.async_call("button", "press",
                                       {"entity_id": ids["terminate_game"]}, blocking=True)
        assert publish.await_count == 1
        async_fire_mqtt_message(hass, ROOT+"/availability","offline")
        await hass.async_block_till_done()
        assert all(hass.states.get(eid).state == "unavailable" for eid in ids.values())
        assert publish.await_count == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_native_mode_no_duplicate_raw_entities(hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN,title=DATA["name"],unique_id="pc1",data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",return_value=False):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor",DOMAIN,"pc1_uptime") is None
    assert registry.async_get_entity_id("button",DOMAIN,"pc1_lock_pc") is None
    assert registry.async_get_entity_id("sensor",DOMAIN,"pc1_daily_budget_remaining") is not None
    assert registry.async_get_entity_id("sensor",DOMAIN,"pc1_weekly_budget_remaining") is not None
    assert registry.async_get_entity_id("switch",DOMAIN,"pc1_unlimited") is not None
    assert registry.async_get_entity_id("switch",DOMAIN,"pc1_gaming_rules_enabled") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_budget_entities_report_percent_and_keep_history_when_offline(hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1",
                            data=DATA, options={"enabled":True,"daily":60,"weekly":300})
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    daily = registry.async_get_entity_id("sensor",DOMAIN,"pc1_daily_budget_remaining")
    weekly = registry.async_get_entity_id("sensor",DOMAIN,"pc1_weekly_budget_remaining")
    c = entry.runtime_data
    with patch("custom_components.hal_gaming_control.sensor.dt_util.now", return_value=__import__("datetime").datetime(2026,11,18,12)):
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
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=True):
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
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(eid).state == "on"
    assert entry.runtime_data.options["unlimited"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_live_budget_controls_and_action_configuration(hass, enable_custom_integrations, mqtt_mock):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1",
                            data=DATA, options={"enabled": True, "daily": 60, "weekly": -1,
                                                "weekend_daily": 120})
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    c = entry.runtime_data
    registry = er.async_get(hass)

    def entity(domain, key):
        return registry.async_get_entity_id(domain, DOMAIN, "pc1_" + key)

    daily = entity("number", "daily_budget")
    weekly = entity("number", "weekly_budget")
    weekend = entity("number", "weekend_bonus")
    bonus = entity("button", "add_daily_budget")
    assert all((daily, weekly, weekend, bonus))
    assert entity("number", "daily_limit") is None
    assert entity("number", "weekly_limit") is None
    assert entity("number", "weekend_daily_limit") is None
    assert entity("select", "add_action") is None
    assert entity("select", "remove_action") is None

    state = hass.states.get(daily)
    assert float(state.state) == 60
    assert state.attributes["min"] == -10
    assert state.attributes["max"] == 600
    assert state.attributes["step"] == 10
    assert state.attributes["mode"] == "slider"
    assert hass.states.get(weekly).attributes["min"] == 0
    assert hass.states.get(weekly).attributes["max"] == 4200
    assert hass.states.get(weekly).attributes["step"] == 60
    assert hass.states.get(weekend).attributes["min"] == 0
    assert hass.states.get(weekend).attributes["max"] == 600
    assert hass.states.get(weekend).attributes["step"] == 10
    assert float(hass.states.get(weekend).state) == 0
    assert entry.options["weekly"] == -1

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        for eid, value in [(daily, 90), (weekly, 4200), (weekend, 180)]:
            await hass.services.async_call("number", "set_value",
                                           {"entity_id": eid, "value": value}, blocking=True)
            await hass.async_block_till_done()
        assert entry.options["daily"] == 90
        assert entry.options["weekly"] == 4200
        assert entry.options["weekend_bonus"] == 180
        assert "weekend_daily" not in entry.options
        # Only daily retains the legacy no-limit notch. Zero is finite for all.
        await hass.services.async_call("number", "set_value",
                                       {"entity_id": daily, "value": -10}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options["daily"] == -1
        for eid, key in [(daily, "daily"), (weekly, "weekly"), (weekend, "weekend_bonus")]:
            await hass.services.async_call("number", "set_value",
                                           {"entity_id": eid, "value": 0}, blocking=True)
            await hass.async_block_till_done()
            assert entry.options[key] == 0

        now = datetime(2026, 11, 21, 12, tzinfo=ZoneInfo("Europe/Zagreb"))
        with patch("custom_components.hal_gaming_control.button.dt_util.now", return_value=now):
            for _ in range(2):
                await hass.services.async_call("button", "press",
                                               {"entity_id": bonus}, blocking=True)
                await hass.async_block_till_done()
            assert entry.options["bonus_minutes"] == 60
            assert entry.options["bonus_date"] == "2026-11-21"
            assert entry.options["weekend_bonus"] == 0
        with patch("custom_components.hal_gaming_control.button.dt_util.now",
                   return_value=now.replace(day=22)):
            await hass.services.async_call("button", "press",
                                           {"entity_id": bonus}, blocking=True)
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
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=direct):
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
async def test_ha_owned_active_game_entity_is_present_in_both_modes(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"],
                            unique_id="pc1", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
               return_value=direct):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, "pc1_active_game")
    for period in ("daily", "weekly"):
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, "pc1_gaming_time_" + period)
    # No process-presence or agent-derived activity entities in either mode.
    for domain, key in (("sensor", "current_game"),
                        ("binary_sensor", "in_game"),
                        ("binary_sensor", "gaming_active")):
        assert registry.async_get_entity_id(domain, DOMAIN, "pc1_" + key) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_ha_owned_active_game_uses_only_v3_not_legacy_scalar_topics(
        hass, enable_custom_integrations, mqtt_mock):
    options = {"tracked_apps": [{"process": "RobloxPlayerBeta.exe",
                                 "signature": None, "name": "Roblox"}]}
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1",
                            data=DATA, options=options)
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
               return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    game = registry.async_get_entity_id("sensor", DOMAIN, "pc1_active_game")
    assert game is not None
    assert registry.async_get_entity_id("sensor", DOMAIN, "pc1_current_game") is None

    async def emit(*messages):
        for suffix, payload in messages:
            async_fire_mqtt_message(hass, ROOT + "/" + suffix, payload)
        await hass.async_block_till_done()

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        await emit(("availability", "online"), ("discovery", discovery_v3()),
                   ("state/current_game", "Roblox"),
                   ("state/active_game", "Roblox"),
                   ("state/gaming_active", "ON"))
        assert hass.states.get(game).state == "unavailable"
        assert entry.runtime_data.foreground._online is True
        assert entry.runtime_data.foreground.v3_capable is True
        await emit(("state/telemetry", v3()))
        assert entry.runtime_data.foreground.telemetry_order.received is not None
        assert hass.states.get(game).state == "Roblox"
        await emit(("state/active_game", "Spoofed Windows label"),
                   ("state/uptime", "9000"))
        assert hass.states.get(game).state == "Roblox"
        await emit(("state/telemetry", v3(seq=2, process="chrome.exe")))
        assert hass.states.get(game).state == "idle"
        await emit(("state/telemetry", v3(seq=3, state="unknown")))
        assert hass.states.get(game).state == "unavailable"
        await emit(("state/telemetry", "{malformed"))
        assert hass.states.get(game).state == "unavailable"
        publish.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_v3_foreground_is_device_scoped_and_resets_on_disconnect(
        hass, enable_custom_integrations, mqtt_mock):
    entries = [
        MockConfigEntry(domain=DOMAIN, title="PC " + pc, unique_id=pc,
                        data={**DATA, "device_id": pc, "name": "PC " + pc},
                        options={"tracked_apps": [{
                            "process": "RobloxPlayerBeta.exe",
                            "signature": None, "name": "Roblox"}]}
                        if pc == "pc1" else {"tracked_apps": []})
        for pc in ("pc1", "pc2")]
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
               return_value=True):
        for entry in entries:
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    ids = {pc: registry.async_get_entity_id(
        "sensor", DOMAIN, pc + "_active_game") for pc in ("pc1", "pc2")}
    assert all(ids.values())

    async def emit(pc, suffix, payload):
        async_fire_mqtt_message(
            hass, f"SmartHouse/Gaming/{pc}/{suffix}", payload)
        await hass.async_block_till_done()

    for pc in ("pc1", "pc2"):
        await emit(pc, "availability", "online")
        await emit(pc, "discovery", discovery_v3(pc))
        await emit(pc, "state/telemetry", v3(pc))
    assert entries[0].runtime_data.foreground._online is True
    assert entries[0].runtime_data.foreground.v3_capable is True
    assert entries[0].runtime_data.foreground.telemetry_order.received is not None
    assert hass.states.get(ids["pc1"]).state == "Roblox"
    assert hass.states.get(ids["pc2"]).state == "idle"
    await emit("pc1", "availability", "offline")
    assert hass.states.get(ids["pc1"]).state == "unavailable"
    assert hass.states.get(ids["pc2"]).state == "idle"
    await emit("pc1", "availability", "online")
    assert hass.states.get(ids["pc1"]).state == "unavailable"
    await emit("pc1", "discovery", discovery_v3("pc1"))
    await emit("pc1", "state/telemetry",
               v3("pc1", seq=1, process="chrome.exe", epoch="c" * 32))
    assert hass.states.get(ids["pc1"]).state == "idle"
    for entry in entries:
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_live_ha_duration_display_is_exact_hms_and_numeric_history_remains(
        hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], unique_id="pc1", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    pretty = registry.async_get_entity_id("sensor", DOMAIN, "pc1_gaming_time_display_daily")
    numeric = registry.async_get_entity_id("sensor", DOMAIN, "pc1_gaming_time_daily")
    weekly_pretty = registry.async_get_entity_id("sensor", DOMAIN, "pc1_gaming_time_display_weekly")
    assert all((pretty, numeric, weekly_pretty))
    entry.runtime_data.async_set_updated_data({
        "ready": True, "online": False, "active_game": "idle",
        "recorded_totals": {"daily": 711 * 60 + 3, "weekly": 12 * 3600 + 9},
        "totals": {"daily": 711 * 60 + 3, "weekly": 12 * 3600 + 9},
    })
    await hass.async_block_till_done()
    assert hass.states.get(pretty).state == "11h 51m 3s"
    assert hass.states.get(weekly_pretty).state == "12h 0m 9s"
    assert hass.states.get(pretty).attributes.get("device_class") is None
    assert hass.states.get(pretty).attributes.get("unit_of_measurement") is None
    assert float(hass.states.get(numeric).state) == 711.05
    assert hass.states.get(numeric).attributes["unit_of_measurement"] == "min"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("direct", [False, True])
async def test_passive_restriction_sensor_runs_in_both_mqtt_modes_and_survives_reload(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry = MockConfigEntry(
        domain=DOMAIN, title=DATA["name"], unique_id="pc1", data=DATA,
        options={"enabled": True, "daily": 60, "weekly": 4200,
                 "actions": ["terminate_game", "lock_pc"]})
    entry.add_to_hass(hass)

    async def boot():
        with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
                   return_value=direct):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

    await boot()
    registry = er.async_get(hass)
    restriction = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "pc1_gaming_restriction")
    active_id = registry.async_get_entity_id("sensor", DOMAIN, "pc1_active_game")
    assert restriction and active_id
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, "pc1_allowed") is None
    assert hass.states.get(restriction).state == "unavailable"

    c = entry.runtime_data
    def sample(ready=True, game="idle", seconds=3600):
        c.async_set_updated_data({
            "ready": ready, "online": ready, "active_game": game if ready else None,
            "active": [game] if ready and game != "idle" else [],
            "totals": {"daily": seconds, "weekly": seconds,
                       "per_game": {"Roblox": 0}} if ready else {},
            "recorded_totals": {"daily": seconds, "weekly": seconds},
        })

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        sample()
        await hass.async_block_till_done()
        assert hass.states.get(restriction).state == "on"
        assert hass.states.get(restriction).attributes["reasons"] == ["daily"]
        # An already-active restriction is still ON as a new game starts;
        # the independent Active game state transition is a second automation trigger.
        sample(game="Roblox")
        await hass.async_block_till_done()
        assert hass.states.get(restriction).state == "on"
        assert hass.states.get(active_id).state == "Roblox"
        sample(ready=False)
        await hass.async_block_till_done()
        assert hass.states.get(restriction).state == "unavailable"
        publish.assert_not_awaited()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await boot()
    assert er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, "pc1_gaming_restriction") == restriction
    assert await hass.config_entries.async_unload(entry.entry_id)



@pytest.mark.parametrize("direct", [True, False])
async def test_rules_opt_in_switch_only_controls_passive_signal(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry = MockConfigEntry(
        domain=DOMAIN, title=DATA["name"], unique_id="pc1", data=DATA,
        options={"enabled": False, "daily": 0, "weekly": 300,
                 "actions": ["terminate_game", "lock_pc"]})
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
               return_value=direct):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    toggle = registry.async_get_entity_id("switch", DOMAIN, "pc1_gaming_rules_enabled")
    restricted = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "pc1_gaming_restriction")
    assert toggle and restricted
    assert hass.states.get(toggle).state == "off"
    c = entry.runtime_data

    def observed():
        c.async_set_updated_data({
            "ready": True, "online": True, "active_game": "idle", "active": [],
            "totals": {"daily": 0, "weekly": 0, "per_game": {}},
        })

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        observed()
        await hass.async_block_till_done()
        assert hass.states.get(restricted).state == "off"
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": toggle}, blocking=True)
        await hass.async_block_till_done()
        assert entry.runtime_data is c
        assert entry.options["enabled"] is True
        assert hass.states.get(toggle).state == "on"
        observed()
        await hass.async_block_till_done()
        assert hass.states.get(restricted).state == "on"
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": toggle}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options["enabled"] is False
        observed()
        await hass.async_block_till_done()
        assert hass.states.get(restricted).state == "off"
        publish.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_direct_terminate_capability_requires_matching_live_agent_metadata():
    from types import SimpleNamespace
    from custom_components.hal_gaming_control.direct_mqtt import DirectAction

    c = SimpleNamespace(device_id="pc1", entry=SimpleNamespace(data={"name": "PC 1"}))
    action = DirectAction(c, "terminate_game")
    action._connected = action._online = True
    assert not action.available  # No metadata received yet: fail closed.

    def report(topic, data):
        with patch.object(action, "async_write_ha_state") as write:
            action._capabilities(SimpleNamespace(topic=topic, payload=json.dumps(data)))
            return write.called

    assert report(ROOT + "/discovery", DATA | {"games": [], "actions": ["lock_pc"]})
    assert not action.available
    assert not report("SmartHouse/Gaming/pc2/discovery", DATA | {"device_id": "pc2"})
    assert not action.available
    assert report(ROOT + "/discovery", DATA)
    assert action.available  # Existing legacy allowlist keeps manual kill.
    assert report(ROOT + "/discovery", DATA | {"actions": ["lock_pc"]})
    assert not action.available
    assert report(ROOT + "/discovery", DATA | {"games": []})
    assert not action.available
    assert report(ROOT + "/discovery", DATA | {"protocol_version": 99})
    assert not action.available
