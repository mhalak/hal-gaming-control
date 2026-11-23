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
                BudgetOverviewSensor(c),
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


def _duration_text(seconds):
    """Human-readable seconds; None must never silently turn into zero."""
    if seconds is None:
        return "Unknown"
    hours, remainder = divmod(max(0, int(round(seconds))), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"


def _budget_overview_text(receipt, *, ready):
    """A compact device-row state plus an explicit, read-only breakdown."""
    status = receipt["daily_budget_status"]
    daily = receipt["daily_remaining_seconds"]
    weekly = receipt["weekly_remaining_seconds"]
    if not ready:
        summary = "Budget data unavailable"
    elif status == "disabled":
        summary = "Gaming rules disabled"
    elif receipt["unlimited_gaming_active"]:
        summary = "Unlimited gaming"
    else:
        today = ("Unlimited" if status == "unlimited"
                 else _duration_text(daily) + " left"
                 if daily is not None else "Unknown")
        weekly_status = receipt["weekly_budget_status"]
        week = ("Unlimited" if weekly_status == "unlimited"
                else _duration_text(weekly) + " left"
                if weekly is not None else "Unknown")
        summary = f"Today: {today} · Week: {week}"

    allowance = receipt["daily_limit_minutes"]
    weekly_limit = receipt["weekly_limit_minutes"]
    lines = [
        f'Daily base: {receipt["base_daily_minutes"]} min'
        if receipt["base_daily_minutes"] is not None else
        "Daily base: Unlimited",
        f'Weekend bonus: +{receipt["weekend_bonus_minutes"]} min',
        f'Parent bonus: +{receipt["parent_bonus_minutes"]} min',
        f'Screen idle bonus: +{receipt["screen_idle_bonus_minutes"]} min',
        "Daily allowance: " + (
            f"{allowance} min" if allowance is not None
            else "Disabled" if status == "disabled" else "Unlimited"),
        "Played today: " + _duration_text(receipt["daily_used_seconds"]),
        "Remaining today: " + (
            _duration_text(daily) if daily is not None
            else "Unknown" if not ready
            else "Disabled" if status == "disabled" else "Unlimited"),
        "Weekly allowance: " + (
            f"{weekly_limit} min" if weekly_limit is not None
            else "Disabled" if receipt["weekly_budget_status"] == "disabled"
            else "Unlimited"),
        "Played this week: " + _duration_text(receipt["weekly_used_seconds"]),
        "Remaining this week: " + (
            _duration_text(weekly) if weekly is not None
            else "Unknown" if not ready
            else "Disabled" if receipt["weekly_budget_status"] == "disabled"
            else "Unlimited"),
    ]
    if receipt["coverage_incomplete"]:
        lines.append("Coverage incomplete: only verified gaming time is counted")
    return summary, "\n".join(lines)


class BudgetOverviewSensor(GamingEntity, SensorEntity):
    """One short text row per PC; full allowance receipt is an attribute."""

    _attr_icon = "mdi:clipboard-text-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "budget_overview", "Budget overview")

    @property
    def available(self):
        # The allowance configuration is HA-owned and readable offline.
        # No fresh/verified gaming data is explicitly marked unavailable.
        return True

    def _receipt(self):
        data = self.coordinator.data or {}
        return budget_overview(
            self.coordinator.options, data.get("totals", {}), dt_util.now(),
            ready=bool(data.get("ready")),
            coverage_incomplete=data.get("coverage_incomplete", True),
        )

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        summary, _ = _budget_overview_text(
            self._receipt(), ready=bool(data.get("ready")))
        return summary

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        _, overview = _budget_overview_text(
            self._receipt(), ready=bool(data.get("ready")))
        return {"overview_text": overview,
                "coverage_incomplete": data.get("coverage_incomplete", True)}


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
        attributes = {
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
        if (display.get("reported_state") is not None
                and display["reported_state"] != display.get("state")):
            # Diagnostic only: the incoming event was not accepted for
            # accounting, so never present it as verified display state.
            attributes["display_reported_state"] = display["reported_state"]
        return attributes


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
