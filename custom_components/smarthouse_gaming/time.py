"""Native per-PC allowed gaming time window. No automatic Windows commands."""
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .entity import GamingEntity


SCHEDULE_TIMES = {
    "schedule_start": ("Weekday allowed from", "mdi:clock-start"),
    "schedule_end": ("Weekday allowed until", "mdi:clock-end"),
    "weekend_schedule_start": ("Weekend allowed from", "mdi:clock-start"),
    "weekend_schedule_end": ("Weekend allowed until", "mdi:clock-end"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([GamingScheduleTime(entry.runtime_data, key)
                        for key in SCHEDULE_TIMES])


class GamingScheduleTime(GamingEntity, TimeEntity):
    """Editable HA-local start/end time from current config-entry options."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key):
        name, icon = SCHEDULE_TIMES[key]
        super().__init__(coordinator, key, name)
        self.key = key
        self._attr_icon = icon

    @property
    def available(self):
        return True  # Schedule can be set while the PC is offline.

    @property
    def native_value(self):
        options = self.coordinator.options
        # When upgrading a single-window installation, weekend hours follow
        # the saved weekday hours until the parent explicitly overrides them.
        key = self.key.removeprefix("weekend_")
        value = options.get(self.key, options.get(key))
        try:
            return time.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    async def async_set_value(self, value):
        if type(value) is not time or value.tzinfo is not None or value.microsecond:
            raise HomeAssistantError("Allowed gaming time must be a local time of day")
        formatted = value.isoformat(timespec="seconds" if value.second else "minutes")
        entry = self.coordinator.entry
        if self.coordinator.options.get(self.key) != formatted:
            # Read current options to preserve concurrently saved budgets/apps.
            self.hass.config_entries.async_update_entry(
                entry, options=dict(entry.options) | {self.key: formatted})
        self.async_write_ha_state()
