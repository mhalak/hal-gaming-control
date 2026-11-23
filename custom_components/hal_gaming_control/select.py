"""Device-scoped native HA selection for safe Parent bonus cancellation.

A select entity contains only the current target. It never revokes by itself.
The two admin-only actions use a short-lived, actor-bound prepare/confirm step.
"""
from time import monotonic

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .entity import GamingEntity
from .budget_select import budget_select_rows
from .parent_bonus import parent_bonus_legacy_today, revoke_parent_grant

UNSELECTED = "Choose a Parent bonus to undo"
UNDO_TTL_SECONDS = 90


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ParentBonusGrantSelect(entry.runtime_data)])


class ParentBonusGrantSelect(GamingEntity, SelectEntity):
    """One immutable grant ID per option, with a transient confirmation guard."""

    _attr_icon = "mdi:backup-restore"

    def __init__(self, coordinator):
        # Preserve unique_id/entity_id so existing Undo service targets survive.
        super().__init__(coordinator, "parent_bonus_undo_target",
                         "Budget overview (Undo)")
        self._selected = UNSELECTED
        self._pending = {}
        self._undo_status = "Choose a grant, then prepare Undo"
        self._prepared_label = None

    @property
    def available(self):
        # Parent config is entirely local to HA; the gaming PC may be offline.
        return True

    def _rows(self, now):
        return budget_select_rows(
            self.coordinator.entry.options, self.coordinator.device_id,
            self.coordinator.data, now)

    def _choices(self, now):
        # The full receipt is visible, but only safe untouched Parent bonus
        # rows can ever become the Undo target.
        return {label: grant_id for label, grant_id in self._rows(now)
                if grant_id is not None}

    @property
    def options(self):
        return [UNSELECTED, *(label for label, _ in self._rows(dt_util.now()))]

    @property
    def current_option(self):
        return self._selected if self._selected in self.options else UNSELECTED

    @property
    def extra_state_attributes(self):
        return {
            "undo_status": self._undo_status,
            "prepared_grant": self._prepared_label,
            "legacy_parent_bonus_minutes": parent_bonus_legacy_today(
                self.coordinator.entry.options, dt_util.now()),
        }

    async def async_select_option(self, option):
        if option not in self.options:
            raise HomeAssistantError("Budget item is no longer active")
        if option != UNSELECTED and option not in self._choices(dt_util.now()):
            # The built-in HA Select has no per-option disabled metadata.
            # This backend check also blocks direct select.select_option calls.
            raise HomeAssistantError(
                "This budget item is locked or the Parent bonus was already used")
        if option != self._selected:
            # Cross-user selection is shared by HA; invalidate all outstanding
            # confirmations rather than risk a different grant being cancelled.
            self._pending.clear()
            self._prepared_label = None
            self._undo_status = "Choose Prepare Undo for the selected grant"
        self._selected = option
        self.async_write_ha_state()

    def prepare(self, actor_id):
        """Freeze the exact selected grant for this authenticated HA user."""
        if not actor_id:
            raise HomeAssistantError("Parent bonus Undo requires an HA user")
        label = self.current_option
        choices = self._choices(dt_util.now())
        if label == UNSELECTED or label not in choices:
            raise HomeAssistantError("Select an active Parent bonus first")
        self._pending[actor_id] = (choices[label], label, monotonic())
        self._prepared_label = label
        self._undo_status = f"Prepared: {label}; confirm within 90 seconds"
        self.async_write_ha_state()

    def confirm(self, actor_id):
        """Commit only the prepared grant of the same HA user and selection."""
        pending = self._pending.get(actor_id)
        if pending is None:
            raise HomeAssistantError("Prepare your own Undo first")
        grant_id, label, prepared_at = pending
        if monotonic() - prepared_at > UNDO_TTL_SECONDS:
            self._pending.pop(actor_id, None)
            raise HomeAssistantError("Prepared Parent bonus Undo expired")
        choices = self._choices(dt_util.now())
        if self.current_option != label or choices.get(label) != grant_id:
            self._pending.pop(actor_id, None)
            raise HomeAssistantError("Parent bonus selection changed; prepare again")
        entry = self.coordinator.entry
        try:
            updated = revoke_parent_grant(
                entry.options, self.coordinator.device_id, grant_id, dt_util.now())
        except ValueError as err:
            self._pending.pop(actor_id, None)
            raise HomeAssistantError(str(err)) from err
        result = self.hass.config_entries.async_update_entry(entry, options=updated)
        if result is False:
            raise HomeAssistantError("Parent bonus cancellation was not saved")
        self._pending.clear()
        self._selected = UNSELECTED
        self._prepared_label = None
        self._undo_status = f"Cancelled: {label}. Today's budget has been recalculated."
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        from .const import DOMAIN
        self.hass.data.setdefault(DOMAIN, {}).setdefault(
            "parent_bonus_undo_selects", {})[self.entity_id] = self

    async def async_will_remove_from_hass(self):
        from .const import DOMAIN
        selectors = self.hass.data.get(DOMAIN, {}).get(
            "parent_bonus_undo_selects", {})
        if selectors.get(self.entity_id) is self:
            selectors.pop(self.entity_id)
        await super().async_will_remove_from_hass()
