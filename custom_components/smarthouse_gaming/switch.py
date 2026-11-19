"""Persistent, per-device live override of automatic gaming restrictions."""
from homeassistant.components.switch import SwitchEntity
from .entity import GamingEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([UnlimitedGamingSwitch(entry.runtime_data)])


class UnlimitedGamingSwitch(GamingEntity, SwitchEntity):
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator):
        super().__init__(coordinator, "unlimited", "Unlimited gaming")

    @property
    def available(self):
        # This HA-local control must work even with the PC offline or before
        # Recorder accounting is ready.
        return True

    @property
    def is_on(self):
        return bool(self.coordinator.options["unlimited"])

    async def _set_override(self, value):
        entry = self.coordinator.entry
        if self.is_on != value:
            self.hass.config_entries.async_update_entry(
                entry, options=dict(entry.options) | {"unlimited": value})
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._set_override(True)

    async def async_turn_off(self, **kwargs):
        await self._set_override(False)
