"""Manual actions and a local Smart Parent Bonus."""
from homeassistant.components.button import ButtonEntity
from .direct_mqtt import DirectAction
from .action_registry import ACTION_REGISTRY
from .entity import GamingEntity
from .smart_parent_control import async_add_smart_bonus
from .penalty_control import async_apply_penalty, async_require_admin

BONUS_INCREMENT = 30


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [AddDailyBudget(c), TerminateTrackedGame(c),
                GamingPenaltyButton(c, False), GamingPenaltyButton(c, True)]
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
        await async_add_smart_bonus(self.hass, self.coordinator, BONUS_INCREMENT)


class TerminateTrackedGame(GamingEntity, ButtonEntity):
    """Existing manual button shares exactly the native action's one-use offer."""

    _attr_icon = "mdi:close-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "terminate_tracked_game", "Terminate active game")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.termination.async_add_listener(self.async_write_ha_state))

    @property
    def available(self):
        return super().available and self.coordinator.termination.available

    async def async_press(self):
        await self.coordinator.termination.async_terminate()


class GamingPenaltyButton(GamingEntity, ButtonEntity):
    """Explicit parent shortcuts, never direct Windows commands."""

    def __init__(self, coordinator, cancel_today):
        self.cancel_today = cancel_today
        key = "cancel_today" if cancel_today else "remove_30_minutes"
        name = "Cancel today's gaming" if cancel_today else "Remove 30 minutes"
        super().__init__(coordinator, key, name)
        self._attr_icon = "mdi:cancel" if cancel_today else "mdi:timer-minus-outline"

    @property
    def available(self):
        return True

    async def async_press(self):
        await async_require_admin(self.hass, getattr(self, "_context", None))
        await async_apply_penalty(self.hass, self.coordinator,
                                  cancel_today=self.cancel_today,
                                  minutes=None if self.cancel_today else 30)
