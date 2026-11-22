"""Home Assistant Screen idle config flow and coordinator journal commit."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hal_gaming_control import coordinator as co
from custom_components.hal_gaming_control.const import DOMAIN
from custom_components.hal_gaming_control.screen_idle_bonus import (
    screen_idle_bonus_total, KEY,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]
T0 = datetime(2026, 11, 22, 16, tzinfo=timezone.utc)
DEVICE = "pc1"


def entry(hass):
    e = MockConfigEntry(
        domain=DOMAIN, title="Gaming PC", unique_id=DEVICE,
        data={"device_id": DEVICE, "name": "Gaming PC",
              "games": [], "actions": []},
        options={"daily": 180, "weekly": 300, "tracked_apps": [],
                 "screen_idle_enabled": False, "weekend_bonus": 0})
    e.add_to_hass(hass)
    return e


async def test_explicit_per_pc_opt_in_requires_preview_acknowledgement(
        hass, enable_custom_integrations):
    e = entry(hass)
    manager = hass.config_entries.options
    init = await manager.async_init(e.entry_id)
    view = await manager.async_configure(init["flow_id"],
                                          {"next_step_id": "screen_idle"})
    assert view["type"] == data_entry_flow.FlowResultType.FORM
    assert view["step_id"] == "screen_idle"
    refused = await manager.async_configure(init["flow_id"], {
        "screen_idle_enabled": True, "screen_idle_acknowledged": False})
    assert refused["type"] == data_entry_flow.FlowResultType.FORM
    assert refused["errors"]["base"] == "screen_idle_preview_unconfirmed"
    assert e.options["screen_idle_enabled"] is False
    saved = await manager.async_configure(init["flow_id"], {
        "screen_idle_enabled": True, "screen_idle_acknowledged": True})
    assert saved["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert saved["data"]["screen_idle_enabled"] is True
    assert saved["data"]["daily"] == 180 and saved["data"]["weekly"] == 300
    assert saved["data"]["tracked_apps"] == []


async def test_source_only_subscribes_screen_when_explicitly_enabled(hass):
    e = entry(hass)
    c = co.GamingCoordinator(hass, e)
    c.cutover_since = 100
    c._saved_segments = ()
    c.storage_healthy = True
    from unittest.mock import AsyncMock
    store = Mock()
    store.async_load = AsyncMock(return_value=())
    store.async_save = AsyncMock()
    source = Mock()
    source.async_start = AsyncMock()
    with patch.object(co, "async_activate_cutover", new=AsyncMock(return_value=100)), \
         patch.object(co, "ForegroundStore", return_value=store), \
         patch.object(co, "ForegroundSource", return_value=source) as constructor:
        await c.async_start_foreground()
    assert constructor.call_args.kwargs == {"intervals": ()}
    await c.async_stop_foreground()

    hass.config_entries.async_update_entry(e, options=dict(e.options,
                                                       screen_idle_enabled=True))
    c2 = co.GamingCoordinator(hass, e)
    with patch.object(co, "async_activate_cutover", new=AsyncMock(return_value=100)), \
         patch.object(co, "ForegroundStore", return_value=store), \
         patch.object(co, "ForegroundSource", return_value=source) as constructor:
        await c2.async_start_foreground()
    assert constructor.call_args.kwargs["screen_enabled"] is True
    assert callable(constructor.call_args.kwargs["on_screen_off"])
    await c2.async_stop_foreground()


async def test_coordinator_screen_off_commits_receipt_once_without_updater_or_commands(hass):
    e = entry(hass)
    hass.config_entries.async_update_entry(e, options=dict(e.options,
                                                       screen_idle_enabled=True))
    c = co.GamingCoordinator(hass, e)
    c.storage_healthy = True
    c.foreground = Mock()
    ts = T0.timestamp()
    event = {"version": 2, "device_id": DEVICE, "observed_at": ts,
             "display_state": "off", "display_event_age_ms": 0,
             "display_epoch": "a" * 32, "display_sequence": 2,
             "display_scope": "windows_console", "power_source": "ac",
             "ac_timeout_seconds": 600, "dc_timeout_seconds": 300,
             "last_input_idle_ms": 600000}
    segments = [(ts-598, ts-2, "tracked-game")]
    with patch.object(co.dt_util, "now", return_value=T0):
        c._screen_off(event, segments)
        first = dict(e.options)
        c._screen_off(event, segments)  # replay must not persist twice
        assert e.options == first
        assert screen_idle_bonus_total(e.options, T0) == 9
    assert len(e.options[KEY]["events"]) == 1
    assert e.options["weekly"] == 300
    assert e.options["daily"] == 180
    c.close()


async def test_coordinator_does_not_grant_with_unhealthy_storage_or_optout(hass):
    e = entry(hass)
    c = co.GamingCoordinator(hass, e)
    c.foreground = Mock()
    with patch.object(co, "maybe_add_screen_idle_grant") as update:
        c._screen_off({"display_state": "off"}, [])
        update.assert_not_called()
        hass.config_entries.async_update_entry(e, options=dict(e.options,
                                                           screen_idle_enabled=True))
        c._screen_off({"display_state": "off"}, [])
        update.assert_not_called()
    c.close()
