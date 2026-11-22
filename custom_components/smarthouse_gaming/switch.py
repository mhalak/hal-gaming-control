"""Persistent, per-device live override of automatic gaming restrictions."""
from homeassistant.components.switch import SwitchEntity
from .entity import GamingEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([UnlimitedGamingSwitch(entry.runtime_data),
                        GamingRulesSwitch(entry.runtime_data)])


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


class GamingRulesSwitch(GamingEntity, SwitchEntity):
    """Explicit parent opt-in to evaluate budget rules, not to issue commands."""

    _attr_icon = "mdi:shield-check-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "gaming_rules_enabled", "Gaming rules enabled")

    @property
    def available(self):
        # HA-local configuration remains usable while the Windows PC is offline.
        return True

    @property
    def is_on(self):
        return bool(self.coordinator.options["enabled"])

    async def _set_rules_enabled(self, value):
        if self.is_on != value:
            entry = self.coordinator.entry
            self.hass.config_entries.async_update_entry(
                entry, options=dict(entry.options) | {"enabled": value})
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._set_rules_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self._set_rules_enabled(False)
