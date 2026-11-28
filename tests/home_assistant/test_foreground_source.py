"""Unified MQTT v3-only foreground source: transport and device isolation."""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.components import mqtt

from custom_components.hal_gaming_control import foreground_source as src
from custom_components.hal_gaming_control.foreground_source import ForegroundSource

pytestmark = pytest.mark.asyncio
ROOT = "SmartHouse/Gaming"
FIXTURE = (Path(__file__).resolve().parents[1] / "contracts" / "v3"
           / "telemetry-foreground.json")
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}


def packet(device, ts, seq, *, process="RobloxPlayerBeta.exe", state="foreground"):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.update(device_id=device, observed_at=ts, sequence=seq)
    data["foreground"].update(
        state=state, process=process if state == "foreground" else None,
        signature=None, sample_age_ms=0)
    data["display"].update(sample_age_ms=0, event_age_ms=100)
    return json.dumps(data)


def message(device, suffix, payload, retain=False):
    return SimpleNamespace(
        topic=f"{ROOT}/{device}/{suffix}", payload=payload, retain=retain)


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


def deliver(callbacks, device, suffix, payload, *, ts=100, retain=False):
    cb = callbacks[f"{ROOT}/{device}/{suffix}"][0]
    with patch.object(src, "time", return_value=ts), \
            patch.object(src, "monotonic", return_value=10000 + ts):
        cb(message(device, suffix, payload, retain))


def discover(callbacks, device):
    deliver(callbacks, device, "discovery", json.dumps({
        "protocol_version": 1, "device_id": device,
        "name": device, "games": [], "actions": [],
        "unified_telemetry_protocol": 3}))


def total(watcher, ts=110):
    return watcher.totals(datetime.fromtimestamp(ts, timezone.utc))["weekly"]


async def test_v3_only_transport_and_confirmed_foreground(hass):
    watcher, cb, changed, unsub = await make_source(hass, "pc1", [ROBLOX])
    assert set(cb) == {
        f"{ROOT}/pc1/availability",
        f"{ROOT}/pc1/discovery",
        f"{ROOT}/pc1/state/telemetry",
        f"{ROOT}/pc1/diagnostics/response"}
    assert cb[f"{ROOT}/pc1/state/telemetry"][1] == 0
    assert f"{ROOT}/pc1/state/foreground_identity" not in cb
    assert f"{ROOT}/pc1/state/display_context" not in cb
    discover(cb, "pc1")
    deliver(cb, "pc1", "availability", "online", ts=99)
    deliver(cb, "pc1", "state/telemetry", packet("pc1", 100, 1), ts=100)
    assert watcher.current(10100) is None  # Fresh ON needs a later foreground sample.
    deliver(cb, "pc1", "state/telemetry", packet("pc1", 102, 2), ts=102)
    assert watcher.current(10102) == "Roblox"
    deliver(cb, "pc1", "state/telemetry", packet("pc1", 104, 3), ts=104)
    assert total(watcher) == 2
    assert changed.call_count >= 4
    watcher.close()
    assert len(unsub) == 5


async def test_v3_rejects_wrong_identity_retained_and_old_protocol(hass):
    watcher, cb, _, _ = await make_source(hass, "pc1", [ROBLOX])
    discover(cb, "pc1")
    deliver(cb, "pc1", "availability", "online")
    assert f"{ROOT}/pc1/state/foreground_identity" not in cb
    deliver(cb, "pc1", "state/telemetry", packet("pc2", 100, 1), ts=100)
    assert watcher.current(10100) is None
    deliver(cb, "pc1", "state/telemetry",
            packet("pc1", 102, 2), ts=102, retain=True)
    assert watcher.current(10102) is None
    deliver(cb, "pc1", "state/telemetry", '{"version": 2}', ts=104)
    assert watcher.current(10104) is None
    assert total(watcher) == 0
    watcher.close()


async def test_v3_devices_stay_separate_through_disconnect(hass):
    a, cb_a, _, _ = await make_source(hass, "pc1", [ROBLOX])
    b, cb_b, _, _ = await make_source(hass, "pc2", [ROBLOX])
    for name, callbacks in (("pc1", cb_a), ("pc2", cb_b)):
        discover(callbacks, name)
        deliver(callbacks, name, "availability", "online")
        deliver(callbacks, name, "state/telemetry", packet(name, 100, 1), ts=100)
        deliver(callbacks, name, "state/telemetry", packet(name, 102, 2), ts=102)
    assert a.current(10102) == "Roblox"
    assert b.current(10102) == "Roblox"
    a._connection(False)
    assert a.current(10102) is None
    assert b.current(10102) == "Roblox"
    a.close()
    b.close()


async def test_partial_subscribe_failure_unsubscribes_earlier_topics(hass):
    unsub = Mock()
    with patch.object(mqtt, "is_connected", return_value=True), \
            patch.object(mqtt, "async_subscribe_connection_status",
                         return_value=unsub), \
            patch.object(mqtt, "async_subscribe",
                         side_effect=RuntimeError("missing MQTT transport")):
        watcher = ForegroundSource(hass, "pc1", [ROBLOX], Mock())
        with pytest.raises(RuntimeError):
            await watcher.async_start()
    unsub.assert_called_once()
    assert watcher.current() is None


async def test_ha_only_broker_reconnect_resumes_same_publisher_without_charging_gap(hass):
    watcher, cb, _, _ = await make_source(hass, "pc1", [ROBLOX])
    discover(cb, "pc1")
    deliver(cb, "pc1", "availability", "online")
    for stamp, seq in ((100, 1), (102, 2), (104, 3)):
        deliver(cb, "pc1", "state/telemetry", packet("pc1", stamp, seq), ts=stamp)
    assert watcher.current(10104) == "Roblox"
    assert total(watcher, 104) == 2
    watcher._connection(False)
    assert watcher.current(10105) is None
    watcher._connection(True)
    discover(cb, "pc1")
    deliver(cb, "pc1", "availability", "online", ts=105)
    # A duplicate sequence is not a recovery sample.
    deliver(cb, "pc1", "state/telemetry", packet("pc1", 104, 3), ts=105)
    assert watcher.current(10105) is None
    for stamp, seq in ((106, 4), (108, 5), (110, 6)):
        deliver(cb, "pc1", "state/telemetry", packet("pc1", stamp, seq), ts=stamp)
    assert watcher.current(10110) == "Roblox"
    assert total(watcher, 110) == 4
    watcher.close()


async def test_future_clock_rejection_is_rate_limited_and_never_fabricates_idle(hass, caplog):
    watcher, cb, _, _ = await make_source(hass, "pc1", [ROBLOX])
    discover(cb, "pc1")
    deliver(cb, "pc1", "availability", "online")
    for stamp, seq in ((100, 1), (102, 2), (104, 3)):
        deliver(cb, "pc1", "state/telemetry", packet("pc1", stamp + 2.6, seq), ts=stamp)
    assert watcher.current(10104) is None
    assert total(watcher, 104) == 0
    assert caplog.text.count("Invalid unified telemetry timestamp") == 1
    for stamp, seq in ((106, 4), (108, 5)):
        deliver(cb, "pc1", "state/telemetry", packet("pc1", stamp, seq), ts=stamp)
    assert watcher.current(10108) == "Roblox"
    watcher.close()
