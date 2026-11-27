"""Shared live Smart Parent Bonus control; HA commits a single journal candidate."""
from datetime import datetime, time

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import DEFAULTS
from .gaming_penalty import active_penalties
from .parent_bonus import _journal
from .rule_engine import inside_weekly_schedule
from .smart_bonus_transaction import prepare_grant, prepare_sync_grant
from .smart_policy import effective_snapshot
from .smart_schedule import _day_boundaries, _utc


def _schedule_ended_today(options, now, device_id):
    """Allow reopening after an actual earlier window, not before today's first window."""
    current = _utc(now)
    midnight = _utc(datetime.combine(now.date(), time.min, tzinfo=now.tzinfo))
    points = _day_boundaries(now.date(), now.tzinfo, options) | {midnight}
    if any(midnight <= point < current and inside_weekly_schedule(
            point.astimezone(now.tzinfo), options) for point in points):
        return True
    for row in _journal(options)["events"]:
        if row["device_id"] != device_id or row["status"] != "active":
            continue
        end = (row.get("smart_adjustments") or {}).get("schedule_end_utc")
        if end and midnight < datetime.fromisoformat(end) <= current:
            return True
    return False


def _live_grant_context(options, device_id, now, totals, *, ready):
    settings = DEFAULTS | options
    if settings["gaming_suspended"]:
        raise ValueError("Gaming is suspended; lift the suspension before granting time")
    if not ready:
        raise ValueError("Verified gaming usage is required before granting a Smart Bonus")
    penalties = active_penalties(settings, device_id, now)
    if any(row["cancel_today"] for row in penalties):
        raise ValueError("Undo today's gaming cancellation before granting extra time")
    snapshot = effective_snapshot(settings, totals, now, device_id, ready=ready,
                                  include_penalties=False)
    if penalties and snapshot.selection.remaining_seconds is not None and (
            snapshot.selection.remaining_seconds < sum(row["seconds"] for row in penalties)):
        raise ValueError("Undo a gaming penalty before granting time against penalty debt")
    if snapshot.selection.status != "limited":
        raise ValueError("Smart Bonus requires enabled rules and a known finite effective budget")
    if snapshot.schedule.remaining_seconds == 0 and not _schedule_ended_today(settings, now, device_id):
        raise ValueError("Cannot reopen schedule before today's first allowed window")
    return snapshot.base_balances, settings if settings["schedule_enabled"] else None


def prepare_live_grant(options, device_id, now, minutes, totals, *, ready):
    balances, schedule = _live_grant_context(options, device_id, now, totals, ready=ready)
    return prepare_grant(options, device_id, now, minutes, balances, schedule)


def prepare_live_sync_grant(options, device_id, now, seconds, totals, *, ready):
    balances, schedule = _live_grant_context(options, device_id, now, totals, ready=ready)
    return prepare_sync_grant(options, device_id, now, seconds, balances, schedule)


async def async_add_smart_bonus(hass, coordinator, minutes):
    """Refresh verified accounting, then prepare and commit without yielding."""
    await coordinator.async_refresh()
    now = dt_util.now()
    data = coordinator.data or {}
    ready = data.get("ready") is True and coordinator.last_update_success is not False
    try:
        candidate = prepare_live_grant(coordinator.entry.options, coordinator.device_id,
                                       now, minutes, data.get("totals", {}), ready=ready)
    except (ValueError, TypeError) as error:
        raise HomeAssistantError(str(error)) from error
    if hass.config_entries.async_update_entry(coordinator.entry, options=candidate) is False:
        raise HomeAssistantError("Parent bonus was not saved")
