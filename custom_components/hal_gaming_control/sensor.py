"""Expose raw telemetry and the two owner-requested budget indicators."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.const import EntityCategory
from homeassistant.util import dt as dt_util
from .direct_mqtt import DirectUptime
from .agent_version import AgentVersionSensor, IntegrationVersionSensor
from .entity import GamingEntity
from .rule_engine import remaining_budget_percent, effective_budget_limit, budget_overview


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [BudgetSensor(c, "daily", "Daily budget remaining"),
                BudgetSensor(c, "weekly", "Weekly budget remaining"),
                ActiveGameSensor(c),
                GamingTimeDisplaySensor(c, "daily", "Daily gaming time"),
                GamingTimeDisplaySensor(c, "weekly", "Weekly gaming time"),
                GamingTimeSensor(c, "daily", "Daily gaming time (minutes)"),
                GamingTimeSensor(c, "weekly", "Weekly gaming time (minutes)"),
                AgentVersionSensor(c), IntegrationVersionSensor(c)]
    if c.direct:
        entities.append(DirectUptime(c))
    async_add_entities(entities)


class BudgetSensor(GamingEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:gamepad-variant-outline"

    def __init__(self, coordinator, period, name):
        super().__init__(coordinator, period + "_budget_remaining", name)
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
            "budget_minutes": limit if limit >= 0 else None,
            "used_minutes": round(used / 60, 2) if used is not None else None,
            "remaining_minutes": round(max(0, limit - used / 60), 2)
                if limit >= 0 and used is not None else None,
        }
        if self.period == "daily":
            attributes.update(budget_overview(
                options, totals, now, ready=bool(data.get("ready")),
                coverage_incomplete=data.get("coverage_incomplete", True)))
        return attributes


class ActiveGameSensor(GamingEntity, SensorEntity):
    """Single HA-owned foreground name, never a Windows-provided legacy label."""

    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator):
        super().__init__(coordinator, "active_game", "Active game")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("active_game")

    @property
    def extra_state_attributes(self):
        # Existing Active game entity carries read-only diagnostics. No new
        # per-field HA entities, no Windows process/window paths, no bonuses.
        data = self.coordinator.data or {}
        display = data.get("display_details") or {}
        return {
            "telemetry_protocol": 3,
            "display_state": display.get("state", "unknown"),
            "display_scope": display.get("scope"),
            "display_event_age_ms": display.get("event_age_ms"),
            "display_ac_timeout_seconds": display.get("ac_timeout_seconds"),
            "display_dc_timeout_seconds": display.get("dc_timeout_seconds"),
            "display_power_source": display.get("power_source"),
            "last_input_idle_ms": display.get("last_input_idle_ms"),
            "system_uptime_seconds": data.get("uptime_seconds"),
        }


class GamingTimeSensor(GamingEntity, SensorEntity):
    """Confirmed-only elapsed time; offline history is marked incomplete."""

    _attr_device_class = SensorDeviceClass.DURATION
    # The original numeric entity remains a duration sensor for graphs/history.
    # A separate text sensor provides true h/m/s because HA's frontend formats
    # native 'h' durations as h/m only and native 'min' as m/s only.
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
        return round(elapsed / 60, 6) if elapsed is not None else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {"coverage_incomplete": data.get("coverage_incomplete", True),
                "cutover_since": data.get("cutover_since")}


class GamingTimeDisplaySensor(GamingTimeSensor):
    """Exact H/M/S for parents, separate from the numeric Recorder sensor."""

    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_entity_category = None

    def __init__(self, coordinator, period, name):
        super().__init__(coordinator, period, name)
        self._attr_unique_id = f"{coordinator.device_id}_gaming_time_display_{period}"

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        raw = data.get("recorded_totals")
        if raw is None or raw.get(self.period) is None:
            return None
        seconds = max(0, int(round(raw[self.period])))
        hours, rest = divmod(seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}h {minutes}m {seconds}s"
