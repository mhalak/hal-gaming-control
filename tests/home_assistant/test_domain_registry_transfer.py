"""HA 2026.10 API proof: migrating owned registry entries across integrations.

No production migration logic, no .storage edits, no MQTT calls and no
removal of real config entries. All IDs here are synthetic, in isolated HA.
"""
from copy import deepcopy

import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import MockConfigEntry

LEGACY = "smarthouse_gaming"
TARGET = "parental"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def entries(hass):
    data = {"device_id": "pc1", "name": "Gaming PC", "protocol_version": 1,
            "games": [], "actions": ["terminate_game", "lock_pc"]}
    options = {
        "enabled": True, "daily": 120, "weekly": 4200,
        "schedule_start": "16:00", "schedule_end": "20:00",
        "weekend_schedule_start": "10:00", "weekend_schedule_end": "22:00",
        "weekend_bonus": 60,
        "tracked_apps": [{"process": "RobloxPlayerBeta.exe",
                          "signature": None, "name": "Roblox"}],
    }
    source = MockConfigEntry(domain=LEGACY, title="Gaming PC", unique_id="pc1",
                             data=data, options=deepcopy(options))
    target = MockConfigEntry(domain=TARGET, title="Gaming PC", unique_id="pc1",
                             data=deepcopy(data), options=deepcopy(options))
    source.add_to_hass(hass)
    target.add_to_hass(hass)
    return source, target


@pytest.fixture
def owned_registry(hass, entries):
    source, _ = entries
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "smarthouse_gaming_pc1")},
        name="Gaming PC")
    entity = entities.async_get_or_create(
        "sensor", LEGACY, "pc1_active_game",
        config_entry=source, device_id=device.id)
    entity = entities.async_update_entity(
        entity.entity_id, name="My own name", icon="mdi:gamepad",
        disabled_by=RegistryEntryDisabler.USER)
    return device, entity


async def test_supported_platform_and_device_move_preserve_registry_identity(
        hass, entries, owned_registry):
    source, target = entries
    device, entity = owned_registry
    devices, registry = dr.async_get(hass), er.async_get(hass)
    original_options = deepcopy(dict(source.options))

    # Public HA APIs, never private registry internals.
    moved_device = devices.async_update_device(
        device.id, new_config_entry_id=target.entry_id)
    moved_entity = registry.async_update_entity_platform(
        entity.entity_id, TARGET, new_config_entry_id=target.entry_id)

    assert moved_device.id == device.id
    assert moved_device.config_entry_id == target.entry_id
    assert moved_device.identifiers == device.identifiers
    assert moved_entity.id == entity.id
    assert moved_entity.entity_id == entity.entity_id
    assert moved_entity.unique_id == entity.unique_id
    assert moved_entity.device_id == device.id
    assert moved_entity.config_entry_id == target.entry_id
    assert moved_entity.platform == TARGET
    assert moved_entity.name == "My own name"
    assert moved_entity.icon == "mdi:gamepad"
    assert moved_entity.disabled_by == RegistryEntryDisabler.USER
    assert registry.async_get_entity_id("sensor", TARGET, entity.unique_id) == entity.entity_id
    assert registry.async_get_entity_id("sensor", LEGACY, entity.unique_id) is None
    assert dict(source.options) == dict(target.options) == original_options


async def test_remove_old_entry_does_not_purge_newly_owned_registry(
        hass, entries, owned_registry):
    source, target = entries
    device, entity = owned_registry
    devices, registry = dr.async_get(hass), er.async_get(hass)

    devices.async_update_device(device.id, new_config_entry_id=target.entry_id)
    registry.async_update_entity_platform(
        entity.entity_id, TARGET, new_config_entry_id=target.entry_id)
    # HA Core's supported remove path clears only source-owned entries.
    await hass.config_entries.async_remove(source.entry_id)
    kept = registry.async_get(entity.entity_id)
    assert kept is not None and kept.config_entry_id == target.entry_id
    assert kept.platform == TARGET
    assert devices.async_get(device.id).config_entry_id == target.entry_id
    assert hass.config_entries.async_get_entry(source.entry_id) is None
    assert hass.config_entries.async_get_entry(target.entry_id) is target


async def test_public_api_can_reverse_transfer_before_old_entry_removed(
        hass, entries, owned_registry):
    source, target = entries
    device, entity = owned_registry
    devices, registry = dr.async_get(hass), er.async_get(hass)

    devices.async_update_device(device.id, new_config_entry_id=target.entry_id)
    registry.async_update_entity_platform(
        entity.entity_id, TARGET, new_config_entry_id=target.entry_id)

    # Roll back while both config entries still exist and are not loaded.
    registry.async_update_entity_platform(
        entity.entity_id, LEGACY, new_config_entry_id=source.entry_id)
    devices.async_update_device(device.id, new_config_entry_id=source.entry_id)

    restored = registry.async_get(entity.entity_id)
    assert restored.id == entity.id
    assert restored.entity_id == entity.entity_id
    assert restored.platform == LEGACY
    assert restored.config_entry_id == source.entry_id
    assert restored.name == entity.name
    assert devices.async_get(device.id).id == device.id
    assert devices.async_get(device.id).config_entry_id == source.entry_id


async def test_independent_native_mqtt_entities_remain_untouched(
        hass, entries, owned_registry):
    source, target = entries
    device, owned = owned_registry
    native_entry = MockConfigEntry(domain="mqtt", title="Broker", data={})
    native_entry.add_to_hass(hass)
    devices, registry = dr.async_get(hass), er.async_get(hass)
    native_device = devices.async_get_or_create(
        config_entry_id=native_entry.entry_id,
        identifiers={("mqtt", "native_telemetry_pc1")}, name="Native MQTT")
    native_entity = registry.async_get_or_create(
        "sensor", "mqtt", "native_pc1_uptime",
        config_entry=native_entry, device_id=native_device.id)

    devices.async_update_device(device.id, new_config_entry_id=target.entry_id)
    registry.async_update_entity_platform(
        owned.entity_id, TARGET, new_config_entry_id=target.entry_id)

    assert registry.async_get(native_entity.entity_id) == native_entity
    assert devices.async_get(native_device.id) == native_device
    assert native_entity.config_entry_id == native_entry.entry_id


async def test_destination_unique_id_collision_rejects_platform_transfer(
        hass, entries, owned_registry):
    _, target = entries
    device, entity = owned_registry
    registry = er.async_get(hass)
    collision = registry.async_get_or_create(
        "sensor", TARGET, entity.unique_id, config_entry=target)
    with pytest.raises(ValueError):
        registry.async_update_entity_platform(
            entity.entity_id, TARGET, new_config_entry_id=target.entry_id)
    assert registry.async_get(entity.entity_id).platform == LEGACY
    assert registry.async_get(collision.entity_id) == collision
