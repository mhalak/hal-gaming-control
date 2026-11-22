"""Manual actions and a local daily budget bonus."""
from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from .direct_mqtt import DirectAction
from .action_registry import ACTION_REGISTRY
from .entity import GamingEntity
from .rule_engine import effective_daily, daily_bonus_minutes

BONUS_INCREMENT = 30


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [AddDailyBudget(c)]
    if c.direct:
        entities.extend(DirectAction(c, key) for key in ACTION_REGISTRY if key in c.advertised)
    async_add_entities(entities)


class AddDailyBudget(GamingEntity, ButtonEntity):
    _attr_icon = "mdi:timer-plus-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "add_daily_budget", "Add 30 minutes")

    @property
    def available(self):
        return True

    async def async_press(self):
        now = dt_util.now()
        options = self.coordinator.options
        if effective_daily(options, now.weekday() >= 5) < 0:
            raise HomeAssistantError("Set a finite daily limit before adding time")
        entry = self.coordinator.entry
        self.hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {
            "bonus_date": now.date().isoformat(),
            "bonus_minutes": daily_bonus_minutes(options, now) + BONUS_INCREMENT,
        })
