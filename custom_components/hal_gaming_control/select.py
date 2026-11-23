"""Per-PC Budget overview with administrator-only, one-tap Parent bonus Undo.

HA SelectEntity displays every allowance row but has no per-option disabled
state. Only rows marked with ⛔ are actions; all other rows are read-only.
The native select service supplies the acting user's context through
Entity.async_set_context. Anonymous and non-admin calls fail closed.
"""
from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .entity import GamingEntity
from .budget_select import TOTAL_ROW_INDEX, budget_select_rows
from .parent_bonus import parent_bonus_legacy_today, revoke_parent_grant


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ParentBonusGrantSelect(entry.runtime_data)])


class ParentBonusGrantSelect(GamingEntity, SelectEntity):
    """The TOTAL subtotal is always selected; bonus Undo stays instant."""

    _attr_icon = "mdi:calculator-variant-outline"

    def __init__(self, coordinator):
        # Keep the original unique ID: existing HA dashboards stay attached.
        super().__init__(coordinator, "parent_bonus_undo_target",
                         "Budget overview (Undo)")
        self._undo_status = "Choose a ⛔ Parent bonus to cancel it immediately"

    @property
    def available(self):
        return True

    def _rows(self, now):
        return budget_select_rows(
            self.coordinator.entry.options, self.coordinator.device_id,
            self.coordinator.data, now)

    def _choices(self, now):
        return {label: grant_id for label, grant_id in self._rows(now)
                if grant_id is not None}

    @property
    def options(self):
        return [label for label, _ in self._rows(dt_util.now())]

    @property
    def current_option(self):
        # Never remember a selected bonus: no repeat-click or stale selection.
        # It also updates automatically when the day's allowance changes.
        return self.options[TOTAL_ROW_INDEX]

    @property
    def extra_state_attributes(self):
        return {
            "undo_status": self._undo_status,
            "legacy_parent_bonus_minutes": parent_bonus_legacy_today(
                self.coordinator.entry.options, dt_util.now()),
        }

    async def _require_admin(self):
        # Core's select service sets context before calling this method.
        # Direct integration calls, scripts, and anonymous actions have no
        # authenticated administrator; never silently remove a bonus.
        context = getattr(self, "_context", None)
        user_id = context.user_id if context is not None else None
        if not user_id:
            raise HomeAssistantError(
                "Cancelling a Parent bonus requires an HA administrator")
        user = await self.hass.auth.async_get_user(user_id)
        if user is None or not user.is_admin:
            raise HomeAssistantError(
                "Cancelling a Parent bonus requires an HA administrator")

    async def async_select_option(self, option):
        now = dt_util.now()
        rows = self._rows(now)
        if option not in (label for label, _ in rows):
            raise HomeAssistantError("Budget entry is no longer active")
        # Clicking selected TOTAL is a no-op. Native select cannot disable
        # read-only items (dividers, played time or remaining budget).
        if option == rows[TOTAL_ROW_INDEX][0]:
            self.async_write_ha_state()
            return
        grant_id = dict(rows).get(option)
        if grant_id is None:
            # An informational row is not a command. Re-publish ∑ TOTAL
            # instead of leaving a misleading selection in the HA UI.
            self._undo_status = "Read-only allowance item; nothing cancelled"
            self.async_write_ha_state()
            return
        await self._require_admin()

        # Refresh confirmed foreground usage before cancellation. The child's
        # measured seconds may have advanced since the dropdown was opened.
        await self.coordinator.async_refresh()
        refreshed = self._choices(dt_util.now())
        if refreshed.get(option) != grant_id:
            raise HomeAssistantError(
                "Parent bonus was used or budget changed; open the list again")
        entry = self.coordinator.entry
        try:
            updated = revoke_parent_grant(
                entry.options, self.coordinator.device_id, grant_id, dt_util.now())
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        result = self.hass.config_entries.async_update_entry(entry, options=updated)
        if result is False:
            raise HomeAssistantError("Parent bonus cancellation was not saved")
        self._undo_status = f"Cancelled: {option}. Allowance recalculated."
        # State always points back to ∑ TOTAL; the grant vanishes
        # immediately as soon as the config-entry update takes effect.
        self.async_write_ha_state()
