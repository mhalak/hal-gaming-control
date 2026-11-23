"""Home Assistant Screen idle config flow and coordinator journal commit."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
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
                 "weekend_bonus": 0})
    e.add_to_hass(hass)
    return e


async def test_screen_idle_is_not_a_config_option(hass, enable_custom_integrations):
    """No UI toggle, acknowledgement or disabling path survives the clean cut."""
    e = entry(hass)
    menu = await hass.config_entries.options.async_init(e.entry_id)
    assert menu["type"].value == "menu"
    assert "screen_idle" not in menu["menu_options"]
    assert "screen_idle_enabled" not in e.options
    assert "screen_idle_acknowledged" not in e.options


async def test_coordinator_always_wires_display_bonus(hass):
    """Fresh PCs need no opt-in to consume verified OFF receipts."""
    from unittest.mock import AsyncMock
    e = entry(hass)
    c = co.GamingCoordinator(hass, e)
    store = Mock()
    store.async_load = AsyncMock(return_value=())
    store.async_save = AsyncMock()
    source = Mock()
    source.async_start = AsyncMock()
    with patch.object(co, "async_activate_cutover", new=AsyncMock(return_value=100)), \
         patch.object(co, "ForegroundStore", return_value=store), \
         patch.object(co, "ForegroundSource", return_value=source) as constructor:
        await c.async_start_foreground()
    assert constructor.call_args.kwargs["intervals"] == ()
    assert callable(constructor.call_args.kwargs["on_screen_off"])
    assert "screen_enabled" not in constructor.call_args.kwargs
    await c.async_stop_foreground()


async def test_coordinator_screen_off_commits_receipt_once_without_updater_or_commands(hass):
    e = entry(hass)
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


async def test_coordinator_does_not_grant_with_unhealthy_storage(hass):
    e = entry(hass)
    c = co.GamingCoordinator(hass, e)
    c.foreground = Mock()
    with patch.object(co, "maybe_add_screen_idle_grant") as update:
        c._screen_off({"display_state": "off"}, [])
        update.assert_not_called()
    c.close()


async def test_obsolete_disabled_flag_cannot_block_award(hass):
    """An existing user's old False toggle is no longer a supported policy."""
    e = entry(hass)
    hass.config_entries.async_update_entry(
        e, options=dict(e.options, screen_idle_enabled=False))
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
    with patch.object(co.dt_util, "now", return_value=T0):
        c._screen_off(event, [(ts-598, ts-2, "roblox")])
    assert screen_idle_bonus_total(e.options, T0) == 9
    c.close()
