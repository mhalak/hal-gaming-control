"""Explicit, fail-closed native MQTT Active game entity-id adoption.

No startup side effects. During an authorized staged agent/HA upgrade:
capture the old native entity_id BEFORE its discovery tombstone, then adopt
the same entity_id for the new HA-owned sensor only AFTER old ownership has
been retired. Recorder rows stay attached to that entity_id unchanged.
"""
import re

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_VALID_ENTRY = re.compile(r"[A-Za-z0-9_-]{1,128}")
_VALID_ENTITY = re.compile(r"sensor\.[a-z0-9_]{1,240}")


class EntityAdoptionBlocked(RuntimeError):
    """Refuse to change identities without complete, verified ownership."""


def _expected(entry):
    device = entry.data.get("device_id")
    if (not isinstance(device, str) or _VALID_ENTRY.fullmatch(device) is None
            or not isinstance(entry.entry_id, str)
            or _VALID_ENTRY.fullmatch(entry.entry_id) is None):
        raise EntityAdoptionBlocked("Invalid config-entry identity")
    return device


def _storage(hass, entry):
    _expected(entry)
    return Store(hass, 1, f"{DOMAIN}.active_game_identity.{entry.entry_id}")


def _saved(payload, device):
    if (not isinstance(payload, dict)
            or payload.keys() != {"version", "device_id", "entity_id"}
            or type(payload["version"]) is not int or payload["version"] != 1
            or payload["device_id"] != device
            or not isinstance(payload["entity_id"], str)
            or _VALID_ENTITY.fullmatch(payload["entity_id"]) is None):
        raise EntityAdoptionBlocked("Untrusted native Active game identity")
    return payload["entity_id"]


def _native(registry, device):
    return registry.async_get_entity_id(
        "sensor", "mqtt", f"smarthouse_gaming_{device}_active_game")


async def async_capture_native_active_game(hass, entry):
    """Snapshot the exact existing MQTT entity ID before agent retirement."""
    device = _expected(entry)
    registry = er.async_get(hass)
    native_id = _native(registry, device)
    if native_id is None:
        raise EntityAdoptionBlocked("Old native Active game not registered")
    entry_row = registry.async_get(native_id)
    if (entry_row is None or entry_row.platform != "mqtt"
            or entry_row.unique_id != f"smarthouse_gaming_{device}_active_game"
            or _VALID_ENTITY.fullmatch(native_id) is None):
        raise EntityAdoptionBlocked("Native entity ownership mismatch")
    store = _storage(hass, entry)
    try:
        existing = await store.async_load()
    except (OSError, ValueError, TypeError) as exc:
        raise EntityAdoptionBlocked("Cannot read saved native identity") from exc
    if existing is not None:
        if _saved(existing, device) != native_id:
            raise EntityAdoptionBlocked("Native Active game identity changed")
        return native_id
    try:
        await store.async_save({
            "version": 1, "device_id": device, "entity_id": native_id})
    except (OSError, ValueError, TypeError) as exc:
        raise EntityAdoptionBlocked("Cannot persist original native identity") from exc
    return native_id


async def async_adopt_native_active_game(hass, entry, *, legacy_retired):
    """Adopt old Recorder entity_id only after exact MQTT retirement evidence."""
    if legacy_retired is not True:
        raise EntityAdoptionBlocked("Native MQTT discovery still authoritative")
    device = _expected(entry)
    try:
        data = await _storage(hass, entry).async_load()
    except (OSError, ValueError, TypeError) as exc:
        raise EntityAdoptionBlocked("Cannot read native identity checkpoint") from exc
    old_id = _saved(data, device)
    registry = er.async_get(hass)
    if _native(registry, device) is not None:
        raise EntityAdoptionBlocked("Old native MQTT entity still registered")
    current = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{device}_active_game")
    if current is None:
        raise EntityAdoptionBlocked("HA-owned Active game is not registered")
    row = registry.async_get(current)
    if row is None or row.config_entry_id != entry.entry_id:
        raise EntityAdoptionBlocked("HA-owned sensor belongs to another entry")
    occupant = registry.async_get(old_id)
    if occupant is not None and occupant.entity_id != current:
        raise EntityAdoptionBlocked("Historic entity_id is occupied")
    if current != old_id:
        registry.async_update_entity(current, new_entity_id=old_id)
    return old_id
