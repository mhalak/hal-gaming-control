"""Read-only, fail-closed snapshot for a future HA integration-domain cutover.

The source integration's domain and entry ID cannot be modified through
Home Assistant's supported config-entry mutation API. This module deliberately
does not attempt an import, entity-registry ownership transfer, or deployment.
"""
from copy import deepcopy

from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN
from .migration_preflight import DESTINATION, async_preflight


class MigrationBlocked(RuntimeError):
    """An exact source snapshot cannot safely be prepared."""

    def __init__(self, reasons):
        self.reasons = tuple(reasons)
        super().__init__("Domain migration preflight blocked: " + ", ".join(self.reasons))


async def async_inventory(hass, entry):
    """Copy source identity/options and exact registry IDs without any writes.

    Results may include private settings; keep in memory on the authorized HA
    host only. Never publish an inventory in logs or a public GitHub issue.
    """
    reasons = await async_preflight(hass, entry)
    if reasons:
        raise MigrationBlocked(reasons)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    owned_devices = dr.async_entries_for_config_entry(devices, entry.entry_id)
    return {
        "source_domain": DOMAIN,
        "target_domain": DESTINATION,
        "source_entry_id": entry.entry_id,
        "device_id": entry.data["device_id"],
        "unique_id": entry.unique_id,
        "title": entry.title,
        "data": deepcopy(dict(entry.data)),
        "options": deepcopy(dict(entry.options)),
        "entity_ids": tuple(sorted(entity.entity_id for entity in entities)),
        "device_ids": tuple(sorted(device.id for device in owned_devices)),
        "updater_store_key": f"smarthouse_gaming.update.{entry.entry_id}",
    }
