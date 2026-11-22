"""ForegroundSource MQTT integration: device isolation and replay safety."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.components import mqtt

from custom_components.parental import foreground_source as src
from custom_components.parental.foreground_source import ForegroundSource

pytestmark = pytest.mark.asyncio

MINECRAFT = {"process": "javaw.exe",
             "signature": {"kind": "java_class",
                           "value": "net.minecraft.client.main.Main"},
             "name": "Minecraft"}
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}


def packet(device, ts, seq, *, process="javaw.exe", signature=None,
           state="foreground", epoch="a" * 32):
    if process == "javaw.exe" and signature is None:
        signature = MINECRAFT["signature"]
    if state != "foreground":
        process = signature = None
    return json.dumps({"version": 2, "device_id": device, "epoch": epoch,
                       "sequence": seq, "observed_at": ts, "state": state,
                       "process": process, "signature": signature})


def message(device, topic, payload, retain=False):
    return SimpleNamespace(
        topic=f"SmartHouse/Gaming/{device}/{topic}",
        payload=payload, retain=retain)


async def make_source(hass, device, apps):
    callbacks, unsubscribed = {}, []
    async def subscribe(_hass, topic, callback, qos=0):
        callbacks[topic] = (callback, qos)
        return lambda: unsubscribed.append(topic)

    notify = Mock()
    with patch.object(mqtt, "is_connected", return_value=True), \
            patch.object(mqtt, "async_subscribe_connection_status",
                         return_value=lambda: unsubscribed.append("connection")), \
            patch.object(mqtt, "async_subscribe", side_effect=subscribe):
        watcher = ForegroundSource(hass, device, apps, notify)
        await watcher.async_start()
    return watcher, callbacks, notify, unsubscribed


def deliver(callbacks, device, topic, payload, *, ts=100, retain=False):
    cb = callbacks[f"SmartHouse/Gaming/{device}/{topic}"][0]
    with patch.object(src, "time", return_value=ts), \
            patch.object(src, "monotonic", return_value=10000 + ts):
        cb(message(device, topic, payload, retain))


def total(watcher, ts=110):
    return watcher.totals(datetime.fromtimestamp(ts, timezone.utc))["weekly"]


async def test_live_foreground_aliases_without_legacy_rules(hass):
    watcher, cb, changed, unsub = await make_source(hass, "pc1", [MINECRAFT, ROBLOX])
    assert cb["SmartHouse/Gaming/pc1/state/foreground_identity"][1] == 0
    assert cb["SmartHouse/Gaming/pc1/availability"][1] == 1
    deliver(cb, "pc1", "availability", b"online")
    deliver(cb, "pc1", "state/foreground_identity", packet("pc1", 100, 1))
    assert watcher.current(10100) == "Minecraft"
    deliver(cb, "pc1", "state/foreground_identity", packet("pc1", 102, 2), ts=102)
    assert total(watcher) == 2
    deliver(cb, "pc1", "state/foreground_identity",
            packet("pc1", 104, 3, process="chrome.exe"), ts=104)
    assert watcher.current(10104) == "idle"
    deliver(cb, "pc1", "state/foreground_identity",
            packet("pc1", 106, 4, process="RobloxPlayerBeta.exe"), ts=106)
    assert watcher.current(10106) == "Roblox"
    assert changed.call_count >= 4
    watcher.close()
    assert len(unsub) == 3
    assert watcher.current(10106) is None


async def test_retained_foreign_stale_and_disconnect_never_count(hass):
    watcher, cb, changed, _ = await make_source(hass, "pc1", [MINECRAFT])
    deliver(cb, "pc1", "state/foreground_identity", packet("pc1", 100, 1))
    assert watcher.current(10100) is None
    deliver(cb, "pc1", "availability", "online")
    deliver(cb, "pc1", "state/foreground_identity",
            packet("pc1", 100, 1), retain=True)
    assert watcher.current(10100) is None
    deliver(cb, "pc1", "state/foreground_identity", packet("pc2", 101, 1), ts=101)
    assert watcher.current(10101) is None
    deliver(cb, "pc1", "state/foreground_identity", packet("pc1", 102, 2), ts=102)
    deliver(cb, "pc1", "state/foreground_identity", packet("pc1", 104, 3), ts=104)
    assert total(watcher) == 2
    deliver(cb, "pc1", "state/foreground_identity", packet("pc1", 90, 4), ts=110)
    assert watcher.current(10110) is None
    assert total(watcher) == 2
    watcher._connection(False)
    assert watcher.current(10110) is None
    deliver(cb, "pc1", "availability", "online")
    assert watcher.current(10110) is None
    watcher.close()


async def test_two_devices_have_independent_connection_and_alias(hass):
    one, callbacks1, _, _ = await make_source(hass, "pc1", [MINECRAFT])
    two, callbacks2, _, _ = await make_source(hass, "pc2", [ROBLOX])
    deliver(callbacks1, "pc1", "availability", "online")
    deliver(callbacks2, "pc2", "availability", "online")
    deliver(callbacks1, "pc1", "state/foreground_identity", packet("pc1", 100, 1))
    deliver(callbacks2, "pc2", "state/foreground_identity",
            packet("pc2", 100, 1, process="RobloxPlayerBeta.exe"))
    assert one.current(10100) == "Minecraft"
    assert two.current(10100) == "Roblox"
    one._connection(False)
    assert one.current(10100) is None
    assert two.current(10100) == "Roblox"
    one.close()
    two.close()


async def test_partial_subscribe_failure_unsubscribes_earlier_topics(hass):
    unsub = Mock()
    with patch.object(mqtt, "is_connected", return_value=True), \
            patch.object(mqtt, "async_subscribe_connection_status",
                         return_value=unsub), \
            patch.object(mqtt, "async_subscribe",
                         side_effect=RuntimeError("missing MQTT transport")):
        watcher = ForegroundSource(hass, "pc1", [MINECRAFT], Mock())
        with pytest.raises(RuntimeError):
            await watcher.async_start()
    unsub.assert_called_once()
    assert watcher.current() is None
