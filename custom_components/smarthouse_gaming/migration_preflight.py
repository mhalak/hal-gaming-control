"""Isolated read-only migration checks; not an onboarding or activation path."""
import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, ROOT
from .protocol import parse_discovery

DESTINATION = "parental"


def _valid_identity(entry):
    device_id = entry.data.get("device_id")
    if not isinstance(device_id, str) or entry.unique_id != device_id:
        return False
    try:
        parse_discovery(f"{ROOT}/{device_id}/discovery", json.dumps(dict(entry.data)))
    except (ValueError, TypeError):
        return False
    return True


def _duplicate_device(hass, entry):
    device_id = entry.data["device_id"]
    return any(
        other.entry_id != entry.entry_id
        and (other.unique_id == device_id or other.data.get("device_id") == device_id)
        for domain in (DOMAIN, DESTINATION)
        for other in hass.config_entries.async_entries(domain)
    )


def _entity_conflict(hass, entry):
    registry = er.async_get(hass)
    return any(
        entity.platform == DOMAIN
        and registry.async_get_entity_id(entity.domain, DESTINATION, entity.unique_id) is not None
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    )


def _update_path(hass, entry):
    # Only this integration's own updater Store, never HA registry storage.
    return Path(Store(hass, 1, f"smarthouse_gaming.update.{entry.entry_id}").path)


def _read_update_state(path):
    # Store.async_load can rename corrupt files or auto-migrate saved versions.
    # Inspect the integration-owned persisted envelope without either side effect.
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (not isinstance(raw, dict) or type(raw.get("version")) is not int
            or raw["version"] != 1 or type(raw.get("minor_version", 1)) is not int
            or raw.get("minor_version", 1) != 1
            or not isinstance(raw.get("data"), dict) or "pending" not in raw["data"]):
        raise ValueError("Unsupported updater storage envelope")
    return raw["data"]


async def _update_problem(hass, entry):
    try:
        saved = await hass.async_add_executor_job(_read_update_state, _update_path(hass, entry))
    except (ValueError, UnicodeError):
        return "update_state_invalid"
    except OSError:
        return "update_state_unavailable"
    if saved is not None and saved["pending"] is not None:
        return "update_pending"
    return None


async def async_preflight(hass, entry):
    """Return blocking reason codes, with no registry, config or storage writes.

    An empty tuple is only a preliminary result; ownership, HA compatibility
    and transactional recovery must be validated before any migration.
    """
    if (entry.domain != DOMAIN or entry.version != 1
            or hass.config_entries.async_get_entry(entry.entry_id) is not entry):
        return ("unsupported_entry",)
    if entry.state is not ConfigEntryState.NOT_LOADED:
        return ("source_not_unloaded",)
    if not _valid_identity(entry):
        return ("invalid_identity",)
    problems = []
    if _duplicate_device(hass, entry):
        problems.append("duplicate_device")
    if _entity_conflict(hass, entry):
        problems.append("entity_conflict")
    if problem := await _update_problem(hass, entry):
        problems.append(problem)
    return tuple(problems)
