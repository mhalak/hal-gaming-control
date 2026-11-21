"""Issue #65: Active game reads the normalized coordinator value in both MQTT modes."""
import json
from unittest.mock import patch

import pytest
from homeassistant.components import mqtt
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.smarthouse_gaming.const import DOMAIN

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

ROOT = "SmartHouse/Gaming"


@pytest.fixture
def expected_lingering_timers():
    return True


def data(pc="pc1"):
    return {"device_id": pc, "name": "Desktop " + pc, "protocol_version": 1,
            "games": ["Roblox"], "actions": ["terminate_game", "lock_pc"]}


async def setup_pc(hass, pc="pc1", *, direct, pre_registered=False):
    entry = MockConfigEntry(domain=DOMAIN, title="Desktop " + pc, unique_id=pc, data=data(pc))
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = None
    if pre_registered:
        old = registry.async_get_or_create(
            "sensor", DOMAIN, pc + "_active_game", config_entry=entry,
            suggested_object_id="legacy_active_game_name").entity_id
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=direct):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, old


def publish(entry, value):
    """Simulate the coordinator publishing its normalized data (Agent B owns the producer)."""
    entry.runtime_data.async_set_updated_data({"ready": True, "online": True, "totals": {},
                                               "reasons": [], "active": [], **value})


def entity_id(hass, pc="pc1"):
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, pc + "_active_game")


async def test_direct_mode_reads_normalized_value_and_keeps_ids(hass, enable_custom_integrations, mqtt_mock):
    entry, old = await setup_pc(hass, direct=True, pre_registered=True)
    eid = entity_id(hass)
    assert eid == old == "sensor.legacy_active_game_name"
    for value, state in [({"active_game": "Roblox"}, "Roblox"), ({"active_game": "idle"}, "idle"),
                         ({"active_game": None}, "unavailable"), ({}, "unavailable"),
                         ({"active_game": "Minecraft"}, "Minecraft"),
                         ({"active_game": ""}, "unavailable"),
                         ({"active_game": "unknown"}, "unavailable"),
                         ({"active_game": 7}, "unavailable")]:
        publish(entry, value)
        await hass.async_block_till_done()
        assert hass.states.get(eid).state == state, value
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_direct_mode_ignores_legacy_mqtt_topics_and_never_publishes(hass, enable_custom_integrations, mqtt_mock):
    entry, _ = await setup_pc(hass, direct=True)
    eid = entity_id(hass)
    with patch.object(mqtt, "async_publish") as outbound:
        for suffix, payload in [("availability", "online"), ("state/current_game", "Roblox"),
                                ("state/in_game", "ON"), ("state/focus_availability", "online"),
                                ("discovery", json.dumps(data() | {"focus_protocol": 1})),
                                ("state/gaming_active", "ON"), ("state/active_game", "Roblox")]:
            async_fire_mqtt_message(hass, f"{ROOT}/pc1/{suffix}", payload)
        await hass.async_block_till_done()
        outbound.assert_not_called()
    assert hass.states.get(eid).state == "unavailable"
    publish(entry, {"active_game": "idle"})
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "idle"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_direct_mode_has_exactly_one_activity_entity(hass, enable_custom_integrations, mqtt_mock):
    entry, _ = await setup_pc(hass, direct=True)
    rows = [e for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
            if e.unique_id.endswith("active_game")]
    assert [(e.domain, e.platform, e.unique_id) for e in rows] == [("sensor", DOMAIN, "pc1_active_game")]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_native_mode_creates_no_competing_active_game_entity(hass, enable_custom_integrations, mqtt_mock):
    registry = er.async_get(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Desktop pc1", unique_id="pc1", data=data())
    entry.add_to_hass(hass)
    # The agent's MQTT-discovery entity owns the native Active game identity.
    native = registry.async_get_or_create("sensor", "mqtt", "smarthouse_gaming_pc1_active_game")
    with patch("custom_components.smarthouse_gaming.coordinator.direct_mode", return_value=False):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entity_id(hass) is None
    publish(entry, {"active_game": "Roblox"})
    await hass.async_block_till_done()
    assert entity_id(hass) is None
    assert registry.async_get(native.entity_id).unique_id == "smarthouse_gaming_pc1_active_game"
    owned = [e.unique_id for e in registry.entities.values() if e.platform == DOMAIN]
    assert not any("active_game" in uid for uid in owned)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_two_pcs_have_independent_values(hass, enable_custom_integrations, mqtt_mock):
    one, _ = await setup_pc(hass, "pc1", direct=True)
    two, _ = await setup_pc(hass, "pc2", direct=True)
    publish(one, {"active_game": "Roblox"})
    publish(two, {"active_game": "idle"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "pc1")).state == "Roblox"
    assert hass.states.get(entity_id(hass, "pc2")).state == "idle"
    publish(one, {"active_game": None})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "pc1")).state == "unavailable"
    assert hass.states.get(entity_id(hass, "pc2")).state == "idle"
    for entry in (one, two):
        assert await hass.config_entries.async_unload(entry.entry_id)
