"""HA-only, device-scoped bonus sync; no Windows commands or peer mutation."""
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .bonus_sync import bonus_entitlement_seconds, sync_difference
from .const import DOMAIN
from .smart_parent_control import prepare_live_sync_grant


def _entitlements(hass, coordinator, now):
    entries = hass.config_entries.async_entries(DOMAIN)
    target = coordinator.entry
    if (target not in entries or target.state != ConfigEntryState.LOADED
            or target.runtime_data is not coordinator):
        raise ValueError("Gaming PC config entry is no longer loaded")
    result = {}
    for entry in entries:
        device = entry.data.get("device_id")
        if not isinstance(device, str) or not device or device in result:
            raise ValueError("Invalid or duplicate gaming PC identity")
        result[device] = bonus_entitlement_seconds(entry.options, device, now)
    return result


async def async_sync_bonus(hass, coordinator):
    """Refresh first, then read all peers and commit without yielding.

    Offline peers can contribute their persisted, validated grant journals.
    The target must be fresh and its policy must permit a Smart Parent Bonus.
    Concurrent clicks are serialized by the synchronous read/commit section.
    """
    await coordinator.async_refresh()
    now = dt_util.now()
    try:
        entitlements = _entitlements(hass, coordinator, now)
        difference = sync_difference(coordinator.device_id, entitlements)
        if not difference:
            return
        data = (coordinator._foreground_data(now)
                if coordinator.foreground is not None else {})
        ready = data.get("ready") is True and coordinator.last_update_success is not False
        entry = coordinator.entry
        candidate = prepare_live_sync_grant(
            entry.options, coordinator.device_id, now, difference,
            data.get("totals", {}), ready=ready)
        if dt_util.now().date() != now.date():
            raise ValueError("Local date changed during bonus sync; try again")
    except (ValueError, TypeError) as error:
        raise HomeAssistantError(str(error)) from error
    if hass.config_entries.async_update_entry(entry, options=candidate) is False:
        raise HomeAssistantError("Sync bonus was not saved")
