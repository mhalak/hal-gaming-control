"""Reset only explicitly selected, UNLOADED HA gaming entries."""
import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming.app_registry import identity_key
from custom_components.smarthouse_gaming.const import DOMAIN
from custom_components.smarthouse_gaming.foreground_cutover import (
    async_activate_cutover,
)
from custom_components.smarthouse_gaming.foreground_store import ForegroundStore
from custom_components.smarthouse_gaming.fresh_start import (
    FreshStartBlocked, async_reset_confirmed_intervals,
)

pytestmark = pytest.mark.asyncio


def config_entry(hass, device):
    entry = MockConfigEntry(
        domain=DOMAIN, title=device, unique_id=device,
        data={"device_id": device, "name": device, "games": [],
              "actions": []},
        options={"tracked_apps": [
            {"process": "RobloxPlayerBeta.exe", "signature": None,
             "name": "Roblox"}], "daily": 90})
    entry.add_to_hass(hass)
    return entry


async def test_reset_clears_only_one_pc_and_keeps_options(hass):
    one, two = config_entry(hass, "pc1"), config_entry(hass, "pc2")
    since1 = await async_activate_cutover(hass, one.entry_id, "pc1")
    since2 = await async_activate_cutover(hass, two.entry_id, "pc2")
    key = identity_key("RobloxPlayerBeta.exe", None)
    first = ForegroundStore(hass, one.entry_id, "pc1")
    second = ForegroundStore(hass, two.entry_id, "pc2")
    await first.async_save(since1, [(since1 + 1, since1 + 3, key)])
    await second.async_save(since2, [(since2 + 1, since2 + 3, key)])
    before = dict(one.options)
    assert await async_reset_confirmed_intervals(
        hass, one, confirm_device_id="pc1") is True
    assert await first.async_load(since1) == ()
    assert await second.async_load(since2) == (
        (since2 + 1, since2 + 3, key),)
    assert dict(one.options) == before
    assert one.options["tracked_apps"][0]["name"] == "Roblox"


async def test_unactivated_entry_has_no_usage_and_is_not_mutated(hass):
    one = config_entry(hass, "pc1")
    assert await async_reset_confirmed_intervals(
        hass, one, confirm_device_id="pc1") is False


async def test_mismatched_device_is_blocked_without_changes(hass):
    one = config_entry(hass, "pc1")
    with pytest.raises(FreshStartBlocked, match="Wrong HA entry"):
        await async_reset_confirmed_intervals(
            hass, one, confirm_device_id="pc2")


async def test_loaded_entry_is_blocked(hass):
    one = config_entry(hass, "pc1")
    original = one.state
    object.__setattr__(one, "state", ConfigEntryState.LOADED)
    try:
        with pytest.raises(FreshStartBlocked, match="Unload"):
            await async_reset_confirmed_intervals(
                hass, one, confirm_device_id="pc1")
    finally:
        object.__setattr__(one, "state", original)
