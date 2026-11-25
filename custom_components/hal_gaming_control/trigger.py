"""Native HA threshold trigger for the authoritative effective-budget sensor."""
from math import isfinite

import probatio
from homeassistant.const import CONF_OPTIONS, EVENT_STATE_CHANGED, STATE_UNKNOWN, STATE_UNAVAILABLE
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.trigger import Trigger

from .const import DOMAIN


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


async def async_get_triggers(hass):
    return {"remaining_budget_reached": RemainingBudgetTrigger}
