"""Coordinator production cutover never counts legacy process-presence telemetry."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hal_gaming_control import coordinator as co
from custom_components.hal_gaming_control.app_registry import identity_key
from custom_components.hal_gaming_control.const import DOMAIN

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


async def test_production_uses_unified_v3_only_and_maps_stable_keys_to_ha_names(hass):
    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    stream = fake_source()
    c.foreground = stream
    c.cutover_since = 99
    c.storage_healthy = True
    assert not hasattr(c, "_prepare_source")
    with patch.object(co.dt_util, "now",
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


async def test_live_unlimited_credit_preserves_raw_totals_and_stable_app_identity(hass):
    from datetime import timedelta
    from custom_components.hal_gaming_control.unlimited_bonus import override_options

    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    stream = fake_source()
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    start = now - timedelta(seconds=90)
    stamp = now.timestamp()
    updated = override_options(obj.options, "pc1", start, "unlimited", True)
    updated = override_options(updated, "pc1", now - timedelta(seconds=30), "unlimited", False)
    hass.config_entries.async_update_entry(obj, options=updated | {"enabled": True})
    stream.export_segments.return_value = ((stamp - 120, stamp, KEY),)
    stream.totals.return_value = {"daily": 120, "weekly": 120, "weekend_total": 0,
                                 "per_game": {KEY: 120}}
    c.foreground = stream
    c.storage_healthy = True
    data = c._foreground_data(now)
    assert data["ready"]
    assert data["recorded_totals"]["daily"] == 120
    assert data["recorded_totals"]["per_game"] == {"Minecraft": 120}
    assert "unlimited_bonus" not in data["recorded_totals"]
    assert data["totals"]["unlimited_bonus"] == {
        "daily": 60, "weekly": 60, "per_game": {"Minecraft": 60}}
    # Offline/unknown samples do not turn a partial interval into a grant.
    stream.current.return_value = None
    offline = c._foreground_data(now)
    assert not offline["ready"] and offline["totals"] == {}
    assert offline["recorded_totals"] == data["recorded_totals"]
    c.close()


async def test_corrupt_unlimited_journal_does_not_invent_credit_or_erase_raw_usage(hass):
    from custom_components.hal_gaming_control.unlimited_bonus import KEY as JOURNAL
    obj = entry(hass)
    c = co.GamingCoordinator(hass, obj)
    c.foreground = fake_source()
    c.storage_healthy = True
    hass.config_entries.async_update_entry(obj, options=obj.options | {
        JOURNAL: {"version": 999, "device_id": "pc1", "intervals": []}})
    data = c._foreground_data(datetime(2026, 11, 23, 12, tzinfo=timezone.utc))
    assert not data["ready"] and data["totals"] == {}
    assert data["recorded_totals"]["daily"] == 2
    assert data["reasons"] is None
    c.close()
