"""HA-local penalty transactions; never publish a Windows command."""
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .gaming_penalty import add_penalty
from .smart_policy import effective_snapshot


async def async_require_admin(hass, context):
    user_id = context.user_id if context is not None else None
    user = await hass.auth.async_get_user(user_id) if user_id else None
    if user is None or not user.is_admin:
        raise HomeAssistantError("Gaming penalties require an HA administrator")


async def async_apply_penalty(hass, coordinator, *, minutes=None, cancel_today=False):
    if not cancel_today:
        await coordinator.async_refresh()
    now = dt_util.now()
    entry = coordinator.entry
    try:
        remaining = None
        if not cancel_today:
            data = coordinator.data or {}
            ready = data.get("ready") is True and coordinator.last_update_success is not False
            snapshot = effective_snapshot(entry.options, data.get("totals", {}),
                                          now, coordinator.device_id, ready=ready)
            if not ready or snapshot.selection.status != "limited":
                raise ValueError("Verified finite remaining gaming time required")
            remaining = snapshot.selection.remaining_seconds
        candidate = add_penalty(entry.options, coordinator.device_id, now,
                                minutes=minutes, remaining_seconds=remaining,
                                cancel_today=cancel_today)
    except (ValueError, TypeError) as error:
        raise HomeAssistantError(str(error)) from error
    if candidate is not entry.options and hass.config_entries.async_update_entry(
            entry, options=candidate) is False:
        raise HomeAssistantError("Gaming penalty was not saved")


def set_gaming_override(hass, coordinator, key, enabled):
    """Persist mutually exclusive parent overrides in one config entry write."""
    if key not in ("gaming_suspended", "unlimited") or type(enabled) is not bool:
        raise HomeAssistantError("Invalid gaming override")
    entry = coordinator.entry
    if key == "unlimited" and enabled and entry.options.get("gaming_suspended"):
        raise HomeAssistantError("Lift the gaming suspension before enabling Unlimited")
    updated = dict(entry.options)
    updated[key] = enabled
    if key == "gaming_suspended" and enabled:
        updated["unlimited"] = False
    if updated != entry.options and hass.config_entries.async_update_entry(
            entry, options=updated) is False:
        raise HomeAssistantError("Gaming override was not saved")
