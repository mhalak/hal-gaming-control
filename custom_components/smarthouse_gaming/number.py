"""Native per-device gaming budgets and additive weekend bonus controls."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.exceptions import HomeAssistantError

from .entity import GamingEntity
from .rule_engine import preview_weekend_bonus_migration

# Keep the established daily/weekly unique IDs to preserve existing user settings,
# dashboard references and Recorder entity history. Weekend bonus is a NEW control:
# reusing the old replacement-limit ID would silently change automation semantics.
CONTROLS = {
    "daily": ("Daily budget", "daily_limit", -10, 600, 10),
    "weekly": ("Weekly budget", "weekly_limit", 0, 4200, 60),
    "weekend_bonus": ("Weekend bonus", "weekend_bonus", 0, 600, 10),
}
# The daily control previously exposed -10 as a no-limit position. Keep its
# meaning; 0 is a real, finite daily budget. Other controls start at zero.
DISABLED_SLIDER_VALUE = -10


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        GamingLimit(entry.runtime_data, key) for key in CONTROLS
    ])


class GamingLimit(GamingEntity, NumberEntity):
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
        if self.key == "weekend_bonus" and "weekend_bonus" not in self.coordinator.entry.options:
            # Read-only equivalent preview. This never migrates or writes policy.
            # An unrepresentable old weekend override stays active until a
            # parent explicitly chooses a new additive bonus.
            try:
                return preview_weekend_bonus_migration(self.coordinator.options)
            except ValueError:
                return None

        value = self.coordinator.options[self.key]
        if self.key == "daily" and value == -1:
            return DISABLED_SLIDER_VALUE
        # Legacy weekly -1 (no cap), non-aligned or over-range saved values must
        # not be guessed, clamped, or silently rewritten to a finite budget.
        return value if isinstance(value, int) and 0 <= value <= self.native_max_value else None

    @property
    def extra_state_attributes(self):
        stored = self.coordinator.entry.options
        if self.key == "weekend_bonus":
            legacy_mode = "weekend_bonus" not in stored
            return {
                "configured_minutes": stored.get("weekend_bonus"),
                "legacy_weekend_override_minutes": stored.get("weekend_daily", -1)
                    if legacy_mode else None,
                "mode": "legacy_override" if legacy_mode else "additive_bonus",
                "requires_manual_resolution": legacy_mode and self.native_value is None,
                "preview_bonus_minutes": self.native_value if legacy_mode else None,
            }
        value = self.coordinator.options[self.key]
        return {
            "configured_minutes": value,
            "disabled_meaning": "No limit" if value == -1 else None,
            "requires_configuration": value == -1 and self.key == "weekly",
            "disabled_slider_value": DISABLED_SLIDER_VALUE if self.key == "daily" else None,
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
            # Explicit owner choice switches policy to the additive key.
            # Old replacement values are not treated as bonus minutes.
            options.pop("weekend_daily", None)
        options[self.key] = configured
        self.hass.config_entries.async_update_entry(entry, options=options)
        self.async_write_ha_state()
