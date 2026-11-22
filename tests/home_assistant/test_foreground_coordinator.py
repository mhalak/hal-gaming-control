"""Coordinator production cutover never counts legacy process-presence telemetry."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming import coordinator as co
from custom_components.smarthouse_gaming.app_registry import identity_key
from custom_components.smarthouse_gaming.const import DOMAIN

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

SIG = {"kind": "java_class", "value": "net.minecraft.client.main.Main"}
APP = {"process": "javaw.exe", "signature": SIG, "name": "Minecraft"}
KEY = identity_key("javaw.exe", SIG)


def entry(hass):
    obj = MockConfigEntry(domain=DOMAIN, title="Gaming PC", unique_id="pc1",
                          data={"device_id": "pc1", "name": "Gaming PC",
                                "games": ["LEGACY"], "actions": ["terminate_game"]},
                          options={"tracked_apps": [APP], "daily": 60})
    obj.add_to_hass(hass)
    return obj


def fake_source():
    source = Mock()
    source.async_start = AsyncMock()
    source.current.return_value = "Minecraft"
    source.totals.return_value = {
        "daily": 2, "weekly": 2, "weekend_total": 0, "per_game": {KEY: 2}}
    source.ledger.apps = {KEY: APP}
    source.export_segments.return_value = ((100, 102, KEY),)
    return source


async def test_production_uses_v2_only_and_maps_stable_keys_to_ha_names(hass):
    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    stream = fake_source()
    c.foreground = stream
    c.cutover_since = 99
    c.storage_healthy = True
    with patch.object(c, "_prepare_source", side_effect=AssertionError(
            "legacy process-presence must never load during v2 cutover")), \
            patch.object(co.dt_util, "now",
                         return_value=datetime(2026, 11, 21, tzinfo=timezone.utc)):
        result = await c._async_update_data()
    assert result["ready"] is True
    assert result["active_game"] == "Minecraft"
    assert result["active"] == ["Minecraft"]
    assert result["totals"]["daily"] == 2
    assert result["totals"]["per_game"] == {"Minecraft": 2}
    assert result["coverage_incomplete"] is True
    assert result["reasons"] == []  # passive policy evaluation never sends commands
    c.close()


async def test_unknown_source_does_not_treat_old_process_as_idle(hass):
    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    stream = fake_source()
    stream.current.return_value = None
    c.foreground = stream
    c.storage_healthy = True
    c.cutover_since = 99
    data = await c._async_update_data()
    assert data["online"] is False
    assert data["ready"] is False
    assert data["active_game"] is None
    assert data["totals"] == {}
    assert data["recorded_totals"]["weekly"] == 2
    assert data["reasons"] is None
    c.close()


async def test_start_reads_ha_apps_and_persistent_confirmed_history(hass):
    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    stream = fake_source()
    store = Mock()
    store.async_load = AsyncMock(return_value=((100, 102, KEY),))
    store.async_save = AsyncMock()
    with patch.object(co, "async_activate_cutover", new=AsyncMock(return_value=99)), \
            patch.object(co, "ForegroundStore", return_value=store), \
            patch.object(co, "ForegroundSource", return_value=stream) as ctor:
        await c.async_start_foreground()
    ctor.assert_called_once()
    args, kwargs = ctor.call_args
    assert args[1] == "pc1"
    assert args[2] == [APP]
    assert kwargs["intervals"] == ((100, 102, KEY),)
    assert c.cutover_since == 99
    assert c.storage_healthy
    await c._async_flush_confirmed()
    store.async_save.assert_not_awaited()
    await c.async_stop_foreground()
    stream.close.assert_called()


async def test_confirmed_new_segment_is_saved_and_storage_error_fails_closed(hass):
    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    c.foreground = fake_source()
    c.foreground_store = Mock()
    c.foreground_store.async_save = AsyncMock()
    c.cutover_since = 99
    c.storage_healthy = True
    await c._async_flush_confirmed()
    c.foreground_store.async_save.assert_awaited_once()
    assert c._saved_segments == ((100, 102, KEY),)
    c.foreground.export_segments.return_value = ((100, 104, KEY),)
    c.foreground_store.async_save.side_effect = co.ForegroundStoreError("disk")
    with patch.object(c, "async_request_refresh", new=AsyncMock()):
        await c._async_flush_confirmed()
        await hass.async_block_till_done()
    assert c.storage_healthy is False
    assert (await c._async_update_data())["ready"] is False
    c.close()


async def test_change_of_ha_application_list_requires_reload(hass):
    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    original = c.policy_options
    hass.config_entries.async_update_entry(
        obj, options=obj.options | {"tracked_apps": [APP | {"name": "Java Minecraft"}]})
    assert c.policy_snapshot(obj.options) != original
    assert obj.options["tracked_apps"][0]["name"] == "Java Minecraft"
    c.close()
