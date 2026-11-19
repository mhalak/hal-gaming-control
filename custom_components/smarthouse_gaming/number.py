"""Native configuration sliders for the three gaming quotas."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.exceptions import HomeAssistantError
from .entity import GamingEntity

LIMITS = {"daily":"Daily limit", "weekend_daily":"Weekend daily limit", "weekly":"Weekly limit"}
# A fixed-step HA number needs an aligned disabled position. Keep -1 in policy.
DISABLED_SLIDER_VALUE = -10


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([GamingLimit(entry.runtime_data, key, name) for key, name in LIMITS.items()])


class GamingLimit(GamingEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = DISABLED_SLIDER_VALUE
    _attr_native_max_value = 600
    _attr_native_step = 10
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator, key + "_limit", name)
        self.key = key

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        value = self.coordinator.options[self.key]
        # Preserve existing policy and larger legacy limits without migration.
        if value == -1:
            return DISABLED_SLIDER_VALUE
        return value if 0 <= value <= 600 else None

    @property
    def extra_state_attributes(self):
        return {"configured_minutes": self.coordinator.options[self.key],
                "disabled_slider_value": DISABLED_SLIDER_VALUE,
                "disabled_meaning": "Use daily limit" if self.key == "weekend_daily" else "No limit"}

    async def async_set_native_value(self, value):
        if value != DISABLED_SLIDER_VALUE and (not 0 <= value <= 600 or value % 10 != 0):
            raise HomeAssistantError("Limit must be -10 (disabled) or 0–600 minutes in 10-minute steps")
        configured = -1 if value == DISABLED_SLIDER_VALUE else int(value)
        entry = self.coordinator.entry
        self.hass.config_entries.async_update_entry(
            entry, options=dict(entry.options) | {self.key: configured})
        self.async_write_ha_state()
