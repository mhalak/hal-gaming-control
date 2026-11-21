"""Native MQTT Active game identity migration must preserve Recorder entity_id."""
import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming.const import DOMAIN
from custom_components.smarthouse_gaming.active_game_identity import (
    EntityAdoptionBlocked, async_capture_native_active_game,
    async_adopt_native_active_game,
)

pytestmark = pytest.mark.asyncio


def entry(hass, device):
    obj = MockConfigEntry(
        domain=DOMAIN, title=device, unique_id=device,
        data={"device_id": device, "name": device, "games": [], "actions": []})
    obj.add_to_hass(hass)
    return obj


def add_native(hass, device, entity_id):
    registry = er.async_get(hass)
    row = registry.async_get_or_create(
        "sensor", "mqtt", f"smarthouse_gaming_{device}_active_game",
        suggested_object_id=f"{device}_old_active")
    return registry.async_update_entity(row.entity_id, new_entity_id=entity_id)


def add_ha(hass, obj):
    row = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, f"{obj.data['device_id']}_active_game",
        config_entry=obj, suggested_object_id="new_active")
    return row


async def test_captured_old_id_is_adopted_only_after_native_retirement(hass):
    obj = entry(hass, "pc1")
    old = add_native(hass, "pc1", "sensor.existing_minecraft_activity")
    new = add_ha(hass, obj)
    assert old.entity_id != new.entity_id
    assert await async_capture_native_active_game(hass, obj) == old.entity_id
    assert await async_capture_native_active_game(hass, obj) == old.entity_id
    with pytest.raises(EntityAdoptionBlocked):
        await async_adopt_native_active_game(hass, obj, legacy_retired=False)
    with pytest.raises(EntityAdoptionBlocked):
        await async_adopt_native_active_game(hass, obj, legacy_retired=True)
    er.async_get(hass).async_remove(old.entity_id)
    assert await async_adopt_native_active_game(
        hass, obj, legacy_retired=True) == old.entity_id
    assert er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "pc1_active_game") == old.entity_id
    assert await async_adopt_native_active_game(
        hass, obj, legacy_retired=True) == old.entity_id


async def test_cross_device_capture_and_wrong_entry_never_change_registry(hass):
    first = entry(hass, "pc1")
    second = entry(hass, "pc2")
    old = add_native(hass, "pc1", "sensor.pc1_original")
    fresh = add_ha(hass, second)
    assert await async_capture_native_active_game(hass, first) == old.entity_id
    with pytest.raises(EntityAdoptionBlocked):
        await async_adopt_native_active_game(hass, second, legacy_retired=True)
    assert er.async_get(hass).async_get(fresh.entity_id) is not None
    assert er.async_get(hass).async_get(old.entity_id) is not None


async def test_missing_capture_does_not_guess_an_old_entity_id(hass):
    obj = entry(hass, "pc1")
    add_ha(hass, obj)
    with pytest.raises(EntityAdoptionBlocked):
        await async_capture_native_active_game(hass, obj)
    with pytest.raises(EntityAdoptionBlocked):
        await async_adopt_native_active_game(hass, obj, legacy_retired=True)


async def test_existing_unrelated_entity_id_blocks_adoption(hass):
    obj = entry(hass, "pc1")
    old = add_native(hass, "pc1", "sensor.old_known_active")
    new = add_ha(hass, obj)
    assert await async_capture_native_active_game(hass, obj) == old.entity_id
    er.async_get(hass).async_remove(old.entity_id)
    other = er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", "unrelated", suggested_object_id="unrelated")
    er.async_get(hass).async_update_entity(
        other.entity_id, new_entity_id=old.entity_id)
    with pytest.raises(EntityAdoptionBlocked):
        await async_adopt_native_active_game(hass, obj, legacy_retired=True)
    assert er.async_get(hass).async_get(new.entity_id) is not None
