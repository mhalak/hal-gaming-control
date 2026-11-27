"""Native HA threshold trigger for the authoritative effective-budget sensor."""
from datetime import timedelta
from math import isfinite
from time import monotonic

import probatio
from homeassistant.const import CONF_OPTIONS, EVENT_STATE_CHANGED, STATE_UNKNOWN, STATE_UNAVAILABLE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.trigger import Trigger

from .const import DOMAIN
from .restriction_dispatch import RestrictionDispatch


def _minutes(value):
    if type(value) is not int or not 0 <= value <= 10080:
        raise probatio.Invalid("Threshold must be 0–10080 whole minutes")
    return value


_SCHEMA = probatio.Schema({
    probatio.Required(CONF_OPTIONS): {
        probatio.Required("minutes"): _minutes,
        probatio.Optional("device_id", default=list): probatio.All(cv.ensure_list, [cv.string]),
    },
})


def _remaining(state):
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    value = state.attributes.get("remaining_seconds")
    if (state.attributes.get("budget_status") != "limited" or type(value) not in (int, float)
            or not isfinite(value) or value < 0):
        return None
    return value


def _crossed(old, new, threshold):
    return (old is not None and new is not None and old > threshold >= new
            and (threshold == 0 or new > 0))


class RemainingBudgetTrigger(Trigger):
    """Fire once per downward threshold crossing on each selected gaming PC."""

    @classmethod
    async def async_validate_config(cls, hass, config):
        return _SCHEMA(config)

    def __init__(self, hass, config):
        super().__init__(hass, config)
        self._threshold = config.options["minutes"] * 60
        self._devices = frozenset(config.options.get("device_id", []))

    async def async_attach_runner(self, run_action, did_not_trigger=None):
        registry = er.async_get(self._hass)

        @callback
        def changed(event):
            old, new = event.data.get("old_state"), event.data.get("new_state")
            before, after = _remaining(old), _remaining(new)
            if not _crossed(before, after, self._threshold):
                return
            entity = registry.async_get(event.data["entity_id"])
            if (entity is None or entity.platform != DOMAIN
                    or not entity.unique_id.endswith("_gaming_budget_remaining")
                    or not entity.device_id
                    or (self._devices and entity.device_id not in self._devices)):
                return
            run_action({"device_id": entity.device_id, "entity_id": new.entity_id,
                        "remaining_seconds": after,
                        "limiting_budget": new.attributes.get("limiting_budget")},
                       "gaming budget reached threshold", event.context)

        return self._hass.bus.async_listen(EVENT_STATE_CHANGED, changed)


_RESTRICTION_SCHEMA = probatio.Schema({
    probatio.Optional(CONF_OPTIONS, default=dict): {
        probatio.Optional("device_id", default=list): probatio.All(cv.ensure_list, [cv.string]),
    },
})


class RestrictionViolatedTrigger(Trigger):
    """Dispatch a verified violation when a matching termination offer exists."""

    @classmethod
    async def async_validate_config(cls, hass, config):
        return _RESTRICTION_SCHEMA(config)

    def __init__(self, hass, config):
        super().__init__(hass, config)
        self._devices = frozenset(config.options.get("device_id", []))

    async def async_attach_runner(self, run_action, did_not_trigger=None):
        registry = dr.async_get(self._hass)
        dispatch = RestrictionDispatch()

        @callback
        def check(_now):
            seen = set()
            for entry in self._hass.config_entries.async_entries(DOMAIN):
                if entry.state != ConfigEntryState.LOADED:
                    continue
                c = entry.runtime_data
                device = registry.async_get_device(
                    identifiers={("mqtt", f"smarthouse_gaming_{c.device_id}")})
                if device is None or (self._devices and device.id not in self._devices):
                    continue
                seen.add(device.id)
                game, reasons = c.restriction_violation()
                token = c.termination.offer["token"] if c.termination.available else None
                if dispatch.should_fire(device.id, game, token, monotonic()):
                    run_action({"device_id": device.id, "active_game": game,
                                "reasons": reasons, "reason": reasons[0]},
                               "gaming restriction violated", Context())
            dispatch.prune(seen)

        # The offer and telemetry are independent MQTT messages. A short
        # interval also covers initial attachment, recovery and missed commands,
        # without depending on the order or enabled state of dashboard entities.
        return async_track_time_interval(self._hass, check, timedelta(seconds=1))


async def async_get_triggers(hass):
    return {"remaining_budget_reached": RemainingBudgetTrigger,
            "restriction_violated": RestrictionViolatedTrigger}
