"""Expose raw telemetry and the two owner-requested budget indicators."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE
from homeassistant.util import dt as dt_util
from .direct_mqtt import DirectUptime, DirectCurrentGame
from .agent_version import AgentVersionSensor, IntegrationVersionSensor
from .entity import GamingEntity
from .rule_engine import remaining_budget_percent, effective_budget_limit, daily_bonus_minutes


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [BudgetSensor(c, "daily", "Daily budget"),
                BudgetSensor(c, "weekly", "Weekly budget"), AgentVersionSensor(c),
                IntegrationVersionSensor(c)]
    if c.direct:
        # Native mode keeps the agent's MQTT-discovery Active game; see ActiveGameSensor.
        entities.extend([DirectUptime(c), DirectCurrentGame(c), ActiveGameSensor(c)])
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


class ActiveGameSensor(GamingEntity, SensorEntity):
    """Active game from the coordinator's normalized value (direct mode only).

    The value is a tracked application's friendly name, ``idle`` or absent.
    Absent means unconfirmed and is shown as unavailable, never as idle. The
    unique ID matches the former direct-mode entity, so the entity ID persists.
    """

    def __init__(self, coordinator):
        super().__init__(coordinator, "active_game", "Active game")

    @property
    def native_value(self):
        value = (self.coordinator.data or {}).get("active_game")
        if (isinstance(value, str) and value.strip()
                and value.casefold() not in ("unknown", "unavailable")):
            return value
        return None

    @property
    def available(self):
        return self.coordinator.last_update_success and self.native_value is not None
