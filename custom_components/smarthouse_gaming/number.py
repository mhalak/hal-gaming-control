"""Native per-device gaming budgets and additive weekend bonus controls."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.exceptions import HomeAssistantError

from .entity import GamingEntity

# Fresh preview: use budget and bonus IDs rather than legacy limit IDs.
CONTROLS = {
    "daily": ("Daily budget", "daily_budget", -10, 600, 10),
    "weekly": ("Weekly budget", "weekly_budget", 0, 4200, 60),
    "weekend_bonus": ("Weekend bonus", "weekend_bonus", 0, 600, 10),
}
# The daily control previously exposed -10 as a no-limit position. Keep its
# meaning; 0 is a real, finite daily budget. Other controls start at zero.
DISABLED_SLIDER_VALUE = -10


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        GamingBudget(entry.runtime_data, key) for key in CONTROLS
    ])


class GamingBudget(GamingEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, key):
        name, unique_key, minimum, maximum, step = CONTROLS[key]
        super().__init__(coordinator, unique_key, name)
        self.key = key
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        if key == "weekend_bonus":
            self._attr_icon = "mdi:gift-outline"

    @property
    def available(self):
        # Budget policy is configured in HA, even while the Windows PC is offline.
        return True

    @property
    def native_value(self):
        value = self.coordinator.options[self.key]
        if self.key == "daily" and value == -1:
            return DISABLED_SLIDER_VALUE
        # Legacy weekly values outside the new scale remain unchanged in config;
        # new installations default to the full 4200-minute weekly allowance.
        return value if type(value) is int and 0 <= value <= self.native_max_value else None

    @property
    def extra_state_attributes(self):
        value = self.coordinator.options[self.key]
        return {
            "configured_minutes": value,
            "disabled_meaning": "No limit" if self.key == "daily" and value == -1 else None,
            "requires_configuration": self.key == "weekly" and value == -1,
        }

    async def async_set_native_value(self, value):
        minimum, maximum, step = CONTROLS[self.key][2:]
        disabled = self.key == "daily" and value == DISABLED_SLIDER_VALUE
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or (not disabled and (not minimum <= value <= maximum or value % step))):
            raise HomeAssistantError(
                f"{self.name} must be {minimum}–{maximum} minutes in {step}-minute steps"
            )
        configured = -1 if disabled else int(value)
        entry = self.coordinator.entry
        options = dict(entry.options)
        if self.key == "weekend_bonus":
            # Discard obsolete replacement budget fields on explicit save.
            options.pop("weekend_daily", None)
            options.pop("weekend_total", None)
        options[self.key] = configured
        self.hass.config_entries.async_update_entry(entry, options=options)
        self.async_write_ha_state()
