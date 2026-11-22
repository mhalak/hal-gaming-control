"""Persistent foreground checkpoint: strict readback and historical rename."""
import json

import pytest

from custom_components.hal_gaming_control.app_registry import identity_key
from custom_components.hal_gaming_control.foreground_store import (
    ForegroundStore, ForegroundStoreError, validate_checkpoint,
)
from custom_components.hal_gaming_control.raw_foreground import HAOwnedForeground

pytestmark = pytest.mark.asyncio

SIGNATURE = {"kind": "java_class", "value": "net.minecraft.client.main.Main"}
JAVA = {"process": "javaw.exe", "signature": SIGNATURE, "name": "Minecraft"}
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}


async def test_roundtrip_survives_new_store_instance_without_live_replay(hass):
    key = identity_key("javaw.exe", SIGNATURE)
    saved = ((101, 103, key), (104, 108, key))
    writer = ForegroundStore(hass, "entry-1", "pc1")
    assert await writer.async_load(100) == ()
    await writer.async_save(100, saved)
    restored = await ForegroundStore(hass, "entry-1", "pc1").async_load(100)
    # Adjacent timestamps need not imply one continuous foreground session.
    assert restored == saved
    tracker = HAOwnedForeground("pc1", [JAVA], intervals=restored)
    assert tracker.current(1000) is None
    assert tracker.export_segments() == saved


async def test_store_is_per_device_and_cutover_epoch(hass):
    key = identity_key("RobloxPlayerBeta.exe", None)
    await ForegroundStore(hass, "entry-a", "pc1").async_save(100, [(100, 102, key)])
    assert await ForegroundStore(hass, "entry-b", "pc2").async_load(100) == ()
    with pytest.raises(ForegroundStoreError):
        await ForegroundStore(hass, "entry-a", "pc1").async_load(101)
    assert await ForegroundStore(hass, "entry-a", "pc1").async_load(100) == (
        (100.0, 102.0, key),)


async def test_renamed_or_removed_game_history_is_still_valid(hass):
    key = identity_key("javaw.exe", SIGNATURE)
    await ForegroundStore(hass, "entry-a", "pc1").async_save(100, [(100, 102, key)])
    restored = await ForegroundStore(hass, "entry-a", "pc1").async_load(100)
    renamed = HAOwnedForeground("pc1", [JAVA | {"name": "Minecraft Java"}],
                                intervals=restored)
    assert renamed.export_segments()[0][2] == key
    # Removing an app must not mutate the saved confirmed historical interval.
    removed = HAOwnedForeground("pc1", [], intervals=restored)
    assert removed.current(1000) is None
    assert removed.export_segments() == restored


@pytest.mark.parametrize("altered", [
    {"version": True},
    {"version": 2},
    {"device_id": "pc2"},
    {"cutover_since": 99},
    {"segments": "not a list"},
    {"segments": [[99, 102, identity_key("RobloxPlayerBeta.exe", None)]]},
    {"segments": [[100, 101, "not a canonical app"]]},
    {"segments": [[100, 102, identity_key("RobloxPlayerBeta.exe", None)],
                  [101, 103, identity_key("RobloxPlayerBeta.exe", None)]]},
])
async def test_corrupt_or_wrong_device_checkpoint_fails_closed(altered):
    original = {"version": 1, "device_id": "pc1", "cutover_since": 100,
                "segments": []}
    with pytest.raises(ForegroundStoreError):
        validate_checkpoint(original | altered, "pc1", 100)


async def test_valid_checkpoint_is_json_serializable(hass):
    key = identity_key("RobloxPlayerBeta.exe", None)
    store = ForegroundStore(hass, "entry-2", "pc2")
    await store.async_save(100, [(100, 102, key)])
    payload = await store.storage.async_load()
    assert json.dumps(payload)
    assert payload["device_id"] == "pc2"
    assert payload["version"] == 1
    assert payload["segments"] == [[100.0, 102.0, key]]
