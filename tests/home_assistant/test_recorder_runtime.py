"""Unified v3 clean-cut: retired scalar Recorder streams are never authoritative.

The durable per-PC verified foreground checkpoints remain covered below.
The former uptime/current_game heartbeat mechanism has been deleted from
production; replaying old retained states cannot grant time or commands.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hal_gaming_control.const import DOMAIN
from custom_components.hal_gaming_control.coordinator import GamingCoordinator

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

TZ = ZoneInfo("Europe/Zagreb")


def at(month, day, hour=0, minute=0, second=0, fold=0):
    return datetime(2026, month, day, hour, minute, second,
                    tzinfo=TZ, fold=fold)


NOW = at(11, 16, 12)
RUNTIME_PKG = (Path(__file__).resolve().parents[2]
               / "custom_components" / "hal_gaming_control")


@pytest.mark.parametrize("scalar_game,scalar_uptime", [
    ("Roblox", "90000"), ("idle", "50"), ("unavailable", "90000"),
])
async def test_old_recorder_scalar_states_cannot_activate_gaming_after_clean_cut(
        hass, scalar_game, scalar_uptime):
    entry = MockConfigEntry(
        domain=DOMAIN, title="PC", unique_id="pc1",
        data={"device_id": "pc1", "name": "PC", "games": ["Roblox"],
              "actions": ["lock_pc"]},
        options={"enabled": True, "daily": 0,
                 "unified_telemetry_enabled": False})
    entry.add_to_hass(hass)
    hass.states.async_set("sensor.pc1_current_game", scalar_game)
    hass.states.async_set("binary_sensor.pc1_in_game", "on")
    hass.states.async_set("sensor.pc1_uptime", scalar_uptime)
    coordinator = GamingCoordinator(hass, entry)

    with patch("homeassistant.components.mqtt.async_publish",
               new_callable=AsyncMock) as publish:
        result = await coordinator._async_update_data()
    assert result == {"ready": False, "online": False}
    assert coordinator.foreground is None
    assert not hasattr(coordinator, "liveness")
    assert not hasattr(coordinator, "_prepare_source")
    publish.assert_not_awaited()
    coordinator.close()


# Durable foreground accounting epoch. This increment is intentionally not
# connected to either coordinator or migration activation.
async def test_foreground_cutover_requires_explicit_activation(hass, freezer):
    from custom_components.hal_gaming_control.foreground_cutover import (
        async_read_cutover, async_activate_cutover)
    freezer.move_to(NOW)
    assert await async_read_cutover(hass, "synthetic-entry-a", "pc1") is None
    assert await async_activate_cutover(hass, "synthetic-entry-a", "pc1") == NOW.timestamp()
    assert await async_read_cutover(hass, "synthetic-entry-a", "pc1") == NOW.timestamp()


async def test_foreground_cutover_is_immutable_across_reload_and_rollover(hass, freezer):
    from custom_components.hal_gaming_control.foreground_cutover import (
        async_read_cutover, async_activate_cutover)
    freezer.move_to(NOW)
    first = await async_activate_cutover(hass, "synthetic-entry-a", "pc1")
    freezer.move_to(at(11, 23, 12))
    assert await async_read_cutover(hass, "synthetic-entry-a", "pc1") == first
    assert await async_activate_cutover(hass, "synthetic-entry-a", "pc1") == first


async def test_foreground_cutover_isolated_between_entries(hass, freezer):
    from custom_components.hal_gaming_control.foreground_cutover import (
        async_read_cutover, async_activate_cutover)
    freezer.move_to(NOW)
    first = await async_activate_cutover(hass, "synthetic-entry-a", "pc1")
    assert await async_read_cutover(hass, "synthetic-entry-b", "pc2") is None
    freezer.move_to(at(11, 16, 13))
    second = await async_activate_cutover(hass, "synthetic-entry-b", "pc2")
    assert first != second
    assert await async_read_cutover(hass, "synthetic-entry-a", "pc1") == first
    assert await async_read_cutover(hass, "synthetic-entry-b", "pc2") == second


async def test_foreground_cutover_rejects_device_identity_mismatch(hass, freezer):
    from custom_components.hal_gaming_control.foreground_cutover import (
        CutoverError, async_read_cutover, async_activate_cutover)
    freezer.move_to(NOW)
    first = await async_activate_cutover(hass, "synthetic-entry-a", "pc1")
    with pytest.raises(CutoverError):
        await async_read_cutover(hass, "synthetic-entry-a", "pc2")
    with pytest.raises(CutoverError):
        await async_activate_cutover(hass, "synthetic-entry-a", "pc2")
    assert await async_read_cutover(hass, "synthetic-entry-a", "pc1") == first


async def test_foreground_cutover_concurrent_activation_is_idempotent(hass, freezer):
    import asyncio
    from custom_components.hal_gaming_control.foreground_cutover import (
        async_read_cutover, async_activate_cutover)
    freezer.move_to(NOW)
    first, second = await asyncio.gather(
        async_activate_cutover(hass, "synthetic-entry-a", "pc1"),
        async_activate_cutover(hass, "synthetic-entry-a", "pc1"))
    assert first == second == NOW.timestamp()
    assert await async_read_cutover(hass, "synthetic-entry-a", "pc1") == first


@pytest.mark.parametrize("invalid", [None, True, "123", -1, float("nan"), float("inf")])
async def test_foreground_cutover_invalid_persisted_data_fails_closed(hass, freezer, invalid):
    from homeassistant.helpers.storage import Store
    from custom_components.hal_gaming_control.foreground_cutover import (
        CutoverError, async_read_cutover, async_activate_cutover)
    freezer.move_to(NOW)
    payload = {"device_id": "pc1", "since": invalid}
    with patch.object(Store, "async_load", new=AsyncMock(return_value=payload)), \
            patch.object(Store, "async_save", new=AsyncMock()) as save:
        with pytest.raises(CutoverError):
            await async_read_cutover(hass, "synthetic-entry-a", "pc1")
        with pytest.raises(CutoverError):
            await async_activate_cutover(hass, "synthetic-entry-a", "pc1")
        save.assert_not_awaited()


async def test_foreground_cutover_save_failure_does_not_return_success(hass, freezer):
    from homeassistant.helpers.storage import Store
    from custom_components.hal_gaming_control.foreground_cutover import (
        CutoverError, async_activate_cutover)
    freezer.move_to(NOW)
    with patch.object(Store, "async_load", new=AsyncMock(return_value=None)), \
            patch.object(Store, "async_save", new=AsyncMock(side_effect=OSError("synthetic"))):
        with pytest.raises(CutoverError):
            await async_activate_cutover(hass, "synthetic-entry-a", "pc1")


@pytest.mark.parametrize("raw", ["{broken", "null", '{"version": 2, "data": {}}'])
async def test_foreground_cutover_corrupt_file_is_never_replaced(hass, raw):
    from homeassistant.helpers.storage import Store
    from custom_components.hal_gaming_control.foreground_cutover import (
        CutoverError, async_read_cutover, async_activate_cutover)
    path = Path(Store(hass, 1, f"{DOMAIN}.foreground_cutover.synthetic-entry-a").path)
    await hass.async_add_executor_job(path.parent.mkdir, 0o700, True, True)
    await hass.async_add_executor_job(path.write_text, raw, "utf-8")
    with pytest.raises(CutoverError):
        await async_read_cutover(hass, "synthetic-entry-a", "pc1")
    with pytest.raises(CutoverError):
        await async_activate_cutover(hass, "synthetic-entry-a", "pc1")
    assert await hass.async_add_executor_job(path.read_text, "utf-8") == raw


async def test_foreground_cutover_silent_save_failure_is_rejected(hass, freezer):
    from homeassistant.helpers.storage import Store
    from custom_components.hal_gaming_control.foreground_cutover import (
        CutoverError, async_activate_cutover)
    freezer.move_to(NOW)
    with patch.object(Store, "async_load", new=AsyncMock(return_value=None)), \
            patch.object(Store, "async_save", new=AsyncMock()):
        with pytest.raises(CutoverError):
            await async_activate_cutover(hass, "synthetic-entry-a", "pc1")


async def test_foreground_cutover_invalid_identifier_rejected(hass):
    from custom_components.hal_gaming_control.foreground_cutover import (
        CutoverError, async_read_cutover)
    with pytest.raises(CutoverError):
        await async_read_cutover(hass, "../outside", "pc1")
