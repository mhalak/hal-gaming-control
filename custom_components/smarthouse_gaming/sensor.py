"""Expose raw telemetry and the two owner-requested budget indicators."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE
from homeassistant.util import dt as dt_util
from .direct_mqtt import DirectUptime, DirectCurrentGame, DirectActiveGame
from .agent_version import AgentVersionSensor
from .entity import GamingEntity
from .rule_engine import remaining_budget_percent, effective_budget_limit, daily_bonus_minutes


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [BudgetSensor(c, "daily", "Daily budget"),
                BudgetSensor(c, "weekly", "Weekly budget"), AgentVersionSensor(c)]
    if c.direct:
        entities.extend([DirectUptime(c), DirectCurrentGame(c), DirectActiveGame(c)])
    async_add_entities(entities)


class BudgetSensor(GamingEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:gamepad-variant-outline"

    def __init__(self, coordinator, period, name):
        super().__init__(coordinator, "budget_" + period, name)
        self.period = period

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        if not data.get("ready"):
            return None
        return remaining_budget_percent(self.coordinator.options, data.get("totals", {}),
                                        dt_util.now(), self.period)


    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        totals = data.get("totals", {})
        now = dt_util.now()
        options = self.coordinator.options
        limit = effective_budget_limit(options, now, self.period)
        used = totals.get(self.period) if data.get("ready") else None
        attributes = {
            "limit_minutes": limit if limit >= 0 else None,
            "used_minutes": round(used / 60, 2) if used is not None else None,
            "remaining_minutes": round(max(0, limit - used / 60), 2)
                if limit >= 0 and used is not None else None,
        }
        if self.period == "daily":
            attributes["bonus_minutes"] = daily_bonus_minutes(options, now)
        return attributes
