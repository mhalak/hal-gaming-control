"""Expose raw telemetry and the two owner-requested budget indicators."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.util import dt as dt_util
from .direct_mqtt import DirectUptime
from .agent_version import AgentVersionSensor, IntegrationVersionSensor
from .entity import GamingEntity
from .rule_engine import remaining_budget_percent, effective_budget_limit, daily_bonus_minutes


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [BudgetSensor(c, "daily", "Daily budget"),
                BudgetSensor(c, "weekly", "Weekly budget"),
                ActiveGameSensor(c),
                GamingTimeSensor(c, "daily", "Daily gaming time"),
                GamingTimeSensor(c, "weekly", "Weekly gaming time"),
                AgentVersionSensor(c), IntegrationVersionSensor(c)]
    if c.direct:
        entities.append(DirectUptime(c))
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
    """Single HA-owned foreground name, never a Windows-provided legacy label."""

    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator):
        super().__init__(coordinator, "active_game", "Active game")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("active_game")


class GamingTimeSensor(GamingEntity, SensorEntity):
    """Confirmed-only elapsed time; offline history is marked incomplete."""

    _attr_device_class = SensorDeviceClass.DURATION
    # Frontend formats fractional hours as h/m/s, avoiding 711m 3s.
    # Keep the numeric duration entity and its stable unique ID for history.
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 6
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, period, name):
        super().__init__(coordinator, "gaming_time_" + period, name)
        self.period = period

    @property
    def available(self):
        data = self.coordinator.data or {}
        if not super().available and not data.get("recorded_totals"):
            return False
        return ("recorded_totals" in data
                and (bool(data.get("ready"))
                     or bool(self.coordinator.foreground.export_segments())))

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        raw = data.get("recorded_totals")
        if raw is None:
            return None
        elapsed = raw.get(self.period)
        # Hours as a fractional value preserve sub-minute precision while
        # letting HA display e.g. 11h 51m 3s rather than 711m 3s.
        return round(elapsed / 3600, 6) if elapsed is not None else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {"coverage_incomplete": data.get("coverage_incomplete", True),
                "cutover_since": data.get("cutover_since")}
