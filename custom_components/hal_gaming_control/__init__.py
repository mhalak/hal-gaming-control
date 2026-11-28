"""SmartHouse Gaming Control integration."""

def _config_entry_only(config):
    """Defer HA imports: the standalone rules work without HA installed."""
    from homeassistant.helpers import config_validation as cv
    from .const import DOMAIN
    return cv.config_entry_only_config_schema(DOMAIN)(config)


CONFIG_SCHEMA = _config_entry_only


async def async_setup(hass, config):
    """Register native actions even when no Windows device is loaded."""
    from .services import async_setup_services
    async_setup_services(hass)
    return True


async def async_setup_entry(hass, entry):
    from homeassistant.components import mqtt
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers.event import async_track_time_interval
    from datetime import timedelta
    from .coordinator import GamingCoordinator
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT unavailable")
    # One clean cut of retired policy switches; preserve every unrelated
    # setting, daily/weekly budget, tracked app and bonus journal.
    obsolete = {"unified_telemetry_enabled", "screen_idle_enabled",
                "screen_idle_acknowledged"}
    if obsolete.intersection(entry.options):
        hass.config_entries.async_update_entry(
            entry, options={key: value for key, value in entry.options.items()
                            if key not in obsolete})
    coordinator = GamingCoordinator(hass, entry)
    try:
        await coordinator.async_start_foreground()
        # Control subscriptions are independent of the foreground accounting
        # lifecycle; unit tests can start raw accounting without an MQTT client.
        await coordinator.termination.async_start()
        await coordinator.popup.async_start()
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        await coordinator.async_stop_foreground()
        coordinator.close()
        raise
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.close)
    # Live MQTT updates can continually defer coordinator polling. Refresh
    # the calendar independently so annual turnover does not rely on silence.
    entry.async_on_unload(async_track_time_interval(
        hass, coordinator._async_refresh_holiday_cache, timedelta(hours=1)))
    # Independent read-only diagnostics must run even when live v3 continually
    # defers coordinator polling or cannot be constructed.
    entry.async_on_unload(async_track_time_interval(
        hass, coordinator.foreground.async_poll_diagnostics, timedelta(seconds=5)))
    # Policy/accounting must run even when the administrative update entity is disabled.
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "binary_sensor", "button", "switch", "number", "time", "select", "update"])
    _remove_legacy_statistics(hass, entry)
    return True


async def _reload(hass, entry):
    coordinator = entry.runtime_data
    if (coordinator.policy_snapshot(entry.options) == coordinator.policy_options
            and dict(entry.data) == coordinator.policy_data):
        # Live gaming setting changes must not interrupt accounting or MQTT subscriptions.
        coordinator.async_update_listeners()
        await coordinator.async_request_refresh()
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "binary_sensor", "button", "switch", "number", "time", "select", "update"])
    if unloaded:
        await entry.runtime_data.async_stop_foreground()
    return unloaded


def _remove_legacy_statistics(hass, entry):
    """Remove only obsolete derived registry entities owned by this config entry."""
    import re
    from homeassistant.helpers import entity_registry as er
    from .const import DOMAIN

    registry = er.async_get(hass)
    prefix = entry.data["device_id"] + "_"
    old_sensors = {
        "played_daily", "played_weekly", "played_weekend_total",
        "budget_overview",
        "remaining_daily", "remaining_weekly", "remaining_weekend_total",
        "restriction", "budget_daily", "budget_weekly",
    }
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform != DOMAIN or not entity.unique_id.startswith(prefix):
            continue
        key = entity.unique_id[len(prefix):]
        domain = entity.entity_id.split(".", 1)[0]
        if ((domain == "sensor" and
             (key in old_sensors or re.fullmatch(r"played_game_[0-9a-f]{16}", key)))
                or (domain == "binary_sensor" and key == "allowed")
                or (domain == "number" and key in {"daily_limit", "weekly_limit", "weekend_daily_limit"})
                or (domain == "select" and key in {"add_action", "remove_action"})):
            registry.async_remove(entity.entity_id)
