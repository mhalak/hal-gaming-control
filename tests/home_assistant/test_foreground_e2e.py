"""Synthetic first enrollment -> persisted HA aliases -> v2 confirmed accounting.

These tests use real HA Options Flow and HA config entries, but no real PCs,
MQTT credentials, live locks, Recorder purges or deployment.
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parental_control import config_flow as cf
from custom_components.parental_control.app_editor import raw_label
from custom_components.parental_control.const import DOMAIN
from custom_components.parental_control.foreground_store import ForegroundStore
from custom_components.parental_control.raw_foreground import HAOwnedForeground

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

JAVA = {"process": "javaw.exe",
        "signature": {"kind": "java_class", "value": "net.minecraft.client.main.Main"}}
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None}
OTHER = {"process": "javaw.exe",
         "signature": {"kind": "java_class", "value": "org.example.other.Main"}}


def entry(hass, device, *, options=None):
    obj = MockConfigEntry(
        domain=DOMAIN, title=device, unique_id=device, options=options or {},
        data={"device_id": device, "name": device, "protocol_version": 1,
              "games": ["Old Java", "Legacy Roblox"],
              "actions": ["lock_pc", "terminate_game"]})
    obj.add_to_hass(hass)
    return obj


async def enroll(hass, obj, identity, name, token):
    candidate = identity | {"token": token, "observed_at": 100}
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=candidate)), \
            patch.object(cf.mqtt, "async_publish",
                         new_callable=AsyncMock) as publish:
        manager = hass.config_entries.options
        view = await manager.async_init(obj.entry_id)
        view = await manager.async_configure(
            view["flow_id"], {"next_step_id": "tracked_apps"})
        existing = [{"name": row["name"], "detected": raw_label(row)}
                    for row in obj.options.get("tracked_apps", [])]
        result = await manager.async_configure(view["flow_id"], {
            "applications": existing + [
                {"name": name, "detected": raw_label(candidate)}]})
        publish.assert_not_called()
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    hass.config_entries.async_update_entry(obj, options=result["data"])


def snapshot(device, time, seq, value, *, state="foreground"):
    return json.dumps({
        "version": 2, "device_id": device, "epoch": "a" * 32,
        "sequence": seq, "observed_at": time, "state": state,
        "process": value["process"] if state == "foreground" else None,
        "signature": value["signature"] if state == "foreground" else None})


def feed(engine, device, ts, seq, identity):
    assert engine.observe(snapshot(device, ts, seq, identity), retained=False,
                          wall_now=ts, monotonic_now=10000 + ts)


def weekly(engine):
    return engine.totals(datetime.fromtimestamp(120, timezone.utc))["weekly"]


async def test_first_enrollment_is_once_and_update_preserves_named_apps(
        hass, enable_custom_integrations):
    obj = entry(hass, "pc1", options={"daily": 120})
    assert obj.options.get("tracked_apps", []) == []
    # The agent's legacy "games" list must not be silently imported.
    await enroll(hass, obj, JAVA, "Minecraft", "a" * 32)
    await enroll(hass, obj, ROBLOX, "Roblox", "b" * 32)
    assert len(obj.options["tracked_apps"]) == 2
    assert obj.options["daily"] == 120
    assert {row["name"] for row in obj.options["tracked_apps"]} == {
        "Minecraft", "Roblox"}

    # Mimic the persistent HA config-entry option payload after an update.
    saved_options = json.loads(json.dumps(dict(obj.options)))
    hass.config_entries.async_update_entry(
        obj, options=saved_options | {"weekly": 360})
    assert obj.options["tracked_apps"] == saved_options["tracked_apps"]

    tracked = HAOwnedForeground("pc1", obj.options["tracked_apps"])
    feed(tracked, "pc1", 100, 1, JAVA)
    feed(tracked, "pc1", 102, 2, JAVA)
    assert tracked.current(10102) == "Minecraft"
    feed(tracked, "pc1", 104, 3, {"process": "chrome.exe", "signature": None})
    assert tracked.current(10104) == "idle"
    feed(tracked, "pc1", 106, 4, ROBLOX)
    feed(tracked, "pc1", 108, 5, ROBLOX)
    assert tracked.current(10108) == "Roblox"
    assert weekly(tracked) == 4

    store = ForegroundStore(hass, obj.entry_id, "pc1")
    await store.async_save(99, tracked.export_segments())
    intervals = await ForegroundStore(hass, obj.entry_id, "pc1").async_load(99)
    restarted = HAOwnedForeground("pc1", obj.options["tracked_apps"],
                                  intervals=intervals)
    # Persisted intervals count, but old live status is unknown on reboot.
    assert restarted.current(10108) is None
    assert weekly(restarted) == 4
    assert obj.options["tracked_apps"] == saved_options["tracked_apps"]


async def test_rename_and_remove_keep_confirmed_old_usage(
        hass, enable_custom_integrations):
    obj = entry(hass, "pc1")
    await enroll(hass, obj, JAVA, "Minecraft", "a" * 32)
    existing = obj.options["tracked_apps"]
    old = HAOwnedForeground("pc1", existing)
    feed(old, "pc1", 100, 1, JAVA)
    feed(old, "pc1", 102, 2, JAVA)
    segments = old.export_segments()
    assert weekly(old) == 2

    manager = hass.config_entries.options
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=None)):
        view = await manager.async_init(obj.entry_id)
        view = await manager.async_configure(
            view["flow_id"], {"next_step_id": "tracked_apps"})
    result = await manager.async_configure(view["flow_id"], {
        "applications": [{"name": "Minecraft Java",
                          "detected": raw_label(JAVA)}]})
    hass.config_entries.async_update_entry(obj, options=result["data"])
    renamed = HAOwnedForeground("pc1", obj.options["tracked_apps"],
                                intervals=segments)
    assert weekly(renamed) == 2
    feed(renamed, "pc1", 104, 3, JAVA)
    assert renamed.current(10104) == "Minecraft Java"
    feed(renamed, "pc1", 106, 4, JAVA)
    assert weekly(renamed) == 4

    removed = HAOwnedForeground("pc1", [], intervals=renamed.export_segments())
    assert weekly(removed) == 4
    feed(removed, "pc1", 108, 5, JAVA)
    assert removed.current(10108) == "idle"
    feed(removed, "pc1", 110, 6, JAVA)
    assert weekly(removed) == 4


async def test_different_java_apps_and_second_pc_do_not_cross_charge(
        hass, enable_custom_integrations):
    first = entry(hass, "pc1")
    second = entry(hass, "pc2")
    await enroll(hass, first, JAVA, "Minecraft", "a" * 32)
    await enroll(hass, second, OTHER, "Other Java", "b" * 32)
    a = HAOwnedForeground("pc1", first.options["tracked_apps"])
    b = HAOwnedForeground("pc2", second.options["tracked_apps"])
    feed(a, "pc1", 100, 1, JAVA)
    feed(a, "pc1", 102, 2, JAVA)
    feed(b, "pc2", 100, 1, OTHER)
    feed(b, "pc2", 102, 2, OTHER)
    assert a.current(10102) == "Minecraft"
    assert b.current(10102) == "Other Java"
    assert weekly(a) == weekly(b) == 2
    assert all(row["name"] != "Other Java"
               for row in first.options["tracked_apps"])
