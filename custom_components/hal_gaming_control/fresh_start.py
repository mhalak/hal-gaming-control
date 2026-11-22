"""Explicit one-time clean start for a single HAL Gaming Control HA entry.

This only resets the v2 verified-interval checkpoint. It does not touch
Home Assistant's shared Recorder database, user policy/options, native MQTT
entities, other PCs or the live Windows agent. Recorder purging remains an
explicit, separately reviewed HA action with exact entity IDs.
"""
from homeassistant.config_entries import ConfigEntryState

from .const import DOMAIN
from .foreground_cutover import async_read_cutover
from .foreground_store import ForegroundStore


class FreshStartBlocked(RuntimeError):
    """Do not reset active or incorrectly scoped gaming data."""


async def async_reset_confirmed_intervals(hass, entry, *, confirm_device_id):
    """Zero this entry's verified time without resetting its tracked apps.

    Run ONLY while the selected HA config entry is unloaded and the
    corresponding Windows source is stopped. Caller must separately review
    and purge exact gaming Recorder entity IDs when that is desired.
    """
    if (entry.domain != DOMAIN
            or not isinstance(confirm_device_id, str)
            or confirm_device_id != entry.data.get("device_id")
            or hass.config_entries.async_get_entry(entry.entry_id) is not entry):
        raise FreshStartBlocked("Wrong HA entry or device ID")
    if entry.state is not ConfigEntryState.NOT_LOADED:
        raise FreshStartBlocked("Unload this HA integration entry before reset")

    since = await async_read_cutover(
        hass, entry.entry_id, confirm_device_id)
    if since is None:
        # The source has not been activated; first normal setup starts empty.
        return False

    store = ForegroundStore(hass, entry.entry_id, confirm_device_id)
    # Never mask corrupt or cross-device records by silently overwriting them.
    await store.async_load(since)
    await store.async_save(since, ())
    if await store.async_load(since) != ():
        raise FreshStartBlocked("Foreground checkpoint reset not verified")
    return True
