"""Issue #65: HA-owned raw MQTT foreground source (both MQTT modes share it)."""
import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components import mqtt
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message, async_fire_time_changed,
)

from custom_components.smarthouse_gaming import foreground_source as module
from custom_components.smarthouse_gaming.app_registry import identity_key
from custom_components.smarthouse_gaming.foreground_source import ForegroundSource

pytestmark = pytest.mark.asyncio

ROOT = "SmartHouse/Gaming"
MINECRAFT = {"process": "javaw.exe",
             "signature": {"kind": "java_class", "value": "net.minecraft.client.main.Main"},
             "name": "Minecraft"}
OTHER = {"process": "javaw.exe",
         "signature": {"kind": "java_class", "value": "org.example.other.Main"},
         "name": "Other Java"}
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}
APPS = [MINECRAFT, OTHER, ROBLOX]
EPOCH = "a" * 32


@pytest.fixture
def expected_lingering_timers():
    return True


class Clock:
    """Controllable wall and monotonic clock injected into the module."""

    def __init__(self):
        self.now = 1_000_000.0

    @property
    def mono(self):
        return self.now + 5_000

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    clk = Clock()
    with patch.object(module, "_wall", lambda: clk.now), \
            patch.object(module, "_mono", lambda: clk.mono):
        yield clk


def raw(clock, seq, *, device="pc1", state="foreground", process="RobloxPlayerBeta.exe",
        signature=None, epoch=EPOCH, observed=None):
    if state != "foreground":
        process = signature = None
    return json.dumps({
        "version": 2, "device_id": device, "epoch": epoch, "sequence": seq,
        "observed_at": clock.now if observed is None else observed,
        "state": state, "process": process, "signature": signature})


def java(app):
    return {"process": app["process"], "signature": app["signature"]}


class Harness:
    def __init__(self, hass, clock, device="pc1", apps=APPS, intervals=()):
        self.hass, self.clock, self.device = hass, clock, device
        self.updates = 0
        self.source = ForegroundSource(hass, device, apps, self._updated, intervals=intervals)
        self.seq = 0

    def _updated(self):
        self.updates += 1

    @property
    def topic(self):
        return f"{ROOT}/{self.device}/state/foreground_identity"

    async def start(self, online=True):
        await self.source.async_start()
        if online:
            await self.availability(b"online")

    async def availability(self, payload):
        async_fire_mqtt_message(self.hass, f"{ROOT}/{self.device}/availability", payload)
        await self.hass.async_block_till_done()

    async def send(self, *, retain=False, **kwargs):
        self.seq += 1
        payload = kwargs.pop("payload", None)
        if payload is None:
            payload = raw(self.clock, kwargs.pop("seq", self.seq), device=self.device, **kwargs)
        async_fire_mqtt_message(self.hass, self.topic, payload, 0, retain)
        await self.hass.async_block_till_done()

    def current(self):
        return self.source.current(self.clock.mono)


@pytest.fixture
async def make(hass, mqtt_mock, clock):
    created = []

    async def factory(online=True, **kwargs):
        harness = Harness(hass, clock, **kwargs)
        created.append(harness)
        await harness.start(online)
        return harness

    yield factory
    for harness in created:
        harness.source.close()


async def test_verified_mapped_application_uses_friendly_name(make):
    h = await make()
    await h.send()
    assert h.current() == "Roblox"
    assert h.updates >= 1


async def test_multiple_java_signatures_are_distinct_apps(make):
    h = await make()
    await h.send(process="javaw.exe", signature=MINECRAFT["signature"])
    assert h.current() == "Minecraft"
    h.clock.advance(2)
    await h.send(process="javaw.exe", signature=OTHER["signature"])
    assert h.current() == "Other Java"
    h.clock.advance(2)
    await h.send(process="javaw.exe", signature={"kind": "java_class", "value": "org.not.enrolled.Main"})
    assert h.current() == "idle"


async def test_bare_java_without_safe_signature_is_unavailable_never_idle(make):
    h = await make()
    await h.send(process="javaw.exe", signature=None)
    assert h.current() is None


async def test_unreported_foreground_is_idle_for_tracked_gameplay(make):
    h = await make()
    await h.send(process="notepad.exe")
    assert h.current() == "idle"
    h.clock.advance(1)
    await h.send(state="idle")
    assert h.current() == "idle"


async def test_alt_tab_never_charges_the_background_game(make):
    h = await make()
    now = h.clock.now
    for step, process in enumerate(["RobloxPlayerBeta.exe", "RobloxPlayerBeta.exe",
                                    "explorer.exe", "RobloxPlayerBeta.exe",
                                    "RobloxPlayerBeta.exe"]):
        await h.send(process=process)
        assert h.current() == ("idle" if process == "explorer.exe" else "Roblox")
        h.clock.advance(2)
    key = identity_key("RobloxPlayerBeta.exe", None)
    # Only two uninterrupted pairs (0-2 and 6-8): the Alt+Tab gap is not charged.
    assert [(s, e, g) for s, e, g in h.source.export_segments()] == [
        (now, now + 2, key), (now + 6, now + 8, key)]
    assert h.source.totals(datetime.fromtimestamp(h.clock.now, timezone.utc))["weekly"] == 4


async def test_unknown_and_offline_are_unavailable_never_idle(make):
    h = await make()
    await h.send()
    assert h.current() == "Roblox"
    h.clock.advance(1)
    await h.send(state="unknown")
    assert h.current() is None
    h.clock.advance(1)
    await h.send()
    assert h.current() == "Roblox"
    before = h.updates
    await h.availability(b"offline")
    assert h.current() is None
    assert h.updates > before
    h.clock.advance(1)
    await h.send()
    assert h.current() is None  # offline until availability returns
    await h.availability(b"online")
    h.clock.advance(1)
    await h.send()
    assert h.current() == "Roblox"


async def test_stale_reading_expires_and_notifies_without_another_message(hass, make, clock):
    h = await make()
    await h.send()
    assert h.current() == "Roblox"
    before = h.updates
    clock.advance(11)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert h.updates > before
    assert h.current() is None


async def test_broker_interruption_is_unavailable_and_recovers_only_on_fresh_data(hass, mqtt_mock, clock):
    callbacks = []
    real = mqtt.async_subscribe_connection_status

    def spy(hass_, cb):
        callbacks.append(cb)
        return real(hass_, cb)

    with patch.object(mqtt, "async_subscribe_connection_status", spy):
        h = Harness(hass, clock)
        await h.start()
    assert len(callbacks) == 1
    await h.send()
    assert h.current() == "Roblox"
    before = h.updates
    callbacks[0](False)
    assert h.current() is None
    assert h.updates > before
    # Data that arrives while the broker link is down is not trusted afterwards.
    clock.advance(1)
    await h.send()
    callbacks[0](True)
    assert h.current() is None
    clock.advance(1)
    await h.send()
    assert h.current() == "Roblox"
    h.source.close()


async def test_retained_message_is_dropped_and_invalidates(make):
    h = await make()
    await h.send()
    assert h.current() == "Roblox"
    with patch.object(h.source, "invalidate", wraps=h.source.invalidate) as invalidate:
        h.clock.advance(1)
        await h.send(retain=True)
        assert invalidate.called
    assert h.current() is None


@pytest.mark.parametrize("bad", ["replay", "old_epoch", "stale", "malformed", "foreign", "binary", "future"])
async def test_rejected_input_invalidates_so_unconfirmed_is_never_idle(make, bad):
    h = await make()
    await h.send(seq=10)
    h.clock.advance(1)
    await h.send(seq=11)
    assert h.current() == "Roblox"
    h.clock.advance(1)
    before = h.updates
    with patch.object(h.source, "invalidate", wraps=h.source.invalidate) as invalidate:
        if bad == "replay":
            await h.send(seq=11)
        elif bad == "old_epoch":
            await h.send(epoch="b" * 32, seq=1, observed=h.clock.now - 1)
        elif bad == "stale":
            await h.send(seq=12, observed=h.clock.now - 30)
        elif bad == "future":
            await h.send(seq=12, observed=h.clock.now + 60)
        elif bad == "malformed":
            await h.send(payload="{not json")
        elif bad == "binary":
            await h.send(payload=b"\xff\xfe\x00")
        else:
            await h.send(payload=raw(h.clock, 12, device="pc2"))
        assert invalidate.called
    assert h.current() is None
    assert h.updates > before


async def test_two_pcs_are_independent(make):
    one, two = await make(device="pc1"), await make(device="pc2")
    await one.send()
    await two.send(state="idle")
    assert (one.current(), two.current()) == ("Roblox", "idle")
    # pc2 data arriving on pc1's topic is foreign and must not leak.
    async_fire_mqtt_message(one.hass, one.topic, raw(one.clock, 99, device="pc2"), 0, False)
    await one.hass.async_block_till_done()
    assert one.current() is None
    assert two.current() == "idle"
    await two.availability(b"offline")
    assert two.current() is None


async def test_subscribes_to_exact_device_topics_only_and_close_releases_all(hass, mqtt_mock, clock):
    subscribed, unsubscribed = [], []
    real_sub, real_conn = mqtt.async_subscribe, mqtt.async_subscribe_connection_status

    async def sub(hass_, topic, cb, *args, **kwargs):
        subscribed.append(topic)
        undo = await real_sub(hass_, topic, cb, *args, **kwargs)

        def release():
            unsubscribed.append(topic)
            undo()
        return release

    def conn(hass_, cb):
        subscribed.append("<connection>")
        undo = real_conn(hass_, cb)

        def release():
            unsubscribed.append("<connection>")
            undo()
        return release

    with patch.object(mqtt, "async_subscribe", sub), \
            patch.object(mqtt, "async_subscribe_connection_status", conn):
        h = Harness(hass, clock)
        await h.start()
        assert sorted(subscribed) == sorted([
            f"{ROOT}/pc1/state/foreground_identity", f"{ROOT}/pc1/availability", "<connection>"])
        assert not any("+" in t or "#" in t for t in subscribed)
        await h.send()
        h.source.close()
        assert sorted(unsubscribed) == sorted(subscribed)
        h.source.close()  # idempotent
        assert len(unsubscribed) == len(subscribed)
    updates = h.updates
    clock.advance(1)
    await h.send()
    await h.availability(b"online")
    assert h.updates == updates
    assert h.source.current(clock.mono) is None


async def test_failed_start_releases_partial_subscriptions(hass, mqtt_mock, clock):
    undone = []
    real = mqtt.async_subscribe
    calls = []

    async def flaky(hass_, topic, cb, *args, **kwargs):
        calls.append(topic)
        if len(calls) == 2:
            raise RuntimeError("broker refused")
        undo = await real(hass_, topic, cb, *args, **kwargs)
        return lambda: (undone.append(topic), undo())

    with patch.object(mqtt, "async_subscribe", flaky):
        h = Harness(hass, clock)
        with pytest.raises(RuntimeError):
            await h.source.async_start()
    assert len(undone) == 1


async def test_nothing_is_ever_published(hass, mqtt_mock, clock, make):
    h = await make()
    with patch.object(mqtt, "async_publish") as publish:
        await h.send()
        await h.send(state="unknown")
        await h.send(payload="garbage")
        await h.availability(b"offline")
        h.source.invalidate()
        h.source.close()
        publish.assert_not_called()
    mqtt_mock.async_publish.assert_not_called()


def test_source_has_no_publish_or_legacy_dependency():
    path = Path(module.__file__)
    tree = ast.parse(path.read_text())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not {"async_publish", "publish", "async_publish_mqtt"} & names
    literals = " ".join(n.value for n in ast.walk(tree)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str))
    assert not any(t in literals for t in ("current_game", "in_game", "active_game", "gaming_active"))


async def test_restart_keeps_history_but_never_bridges_the_gap(make, clock):
    first = await make()
    start = clock.now
    await first.send()
    clock.advance(2)
    await first.send()
    segments = first.source.export_segments()
    assert len(segments) == 1
    first.source.close()
    clock.advance(600)
    second = await make(intervals=segments)
    assert second.current() is None
    assert second.source.export_segments() == segments
    await second.send()
    assert second.current() == "Roblox"
    assert second.source.export_segments() == segments  # first sample alone charges nothing
    assert segments[0][:2] == (start, start + 2)


async def test_alias_rename_keeps_history_and_stable_key(make, clock):
    old = await make()
    await old.send()
    clock.advance(3)
    await old.send()
    segments = old.source.export_segments()
    stamp = datetime.fromtimestamp(clock.now, timezone.utc)
    before = old.source.totals(stamp)
    old.source.close()
    renamed = [dict(app, name="Blocks") if app is ROBLOX else app for app in APPS]
    new = await make(apps=renamed, intervals=segments)
    clock.advance(1)
    await new.send(seq=500, epoch="c" * 32)
    assert new.current() == "Blocks"
    assert new.source.export_segments() == segments
    assert new.source.totals(stamp) == before
    assert segments[0][2] == identity_key("RobloxPlayerBeta.exe", None)


async def test_totals_and_export_delegate_to_ledger(make, clock):
    h = await make()
    await h.send()
    clock.advance(4)
    await h.send()
    assert h.source.totals(datetime.fromtimestamp(clock.now, timezone.utc))["weekly"] == 4
    assert len(h.source.export_segments()) == 1


async def test_on_update_failure_cannot_break_message_handling(hass, mqtt_mock, clock):
    callback = MagicMock(side_effect=RuntimeError("listener bug"))
    source = ForegroundSource(hass, "pc1", APPS, callback)
    await source.async_start()
    async_fire_mqtt_message(hass, f"{ROOT}/pc1/availability", b"online")
    await hass.async_block_till_done()
    async_fire_mqtt_message(hass, f"{ROOT}/pc1/state/foreground_identity", raw(clock, 1), 0, False)
    await hass.async_block_till_done()
    assert source.current(clock.mono) == "Roblox"
    source.close()


async def test_data_received_while_offline_is_not_trusted_when_agent_returns(make):
    h = await make(online=False)
    await h.send()
    await h.availability(b"online")
    assert h.current() is None
    h.clock.advance(1)
    await h.send()
    assert h.current() == "Roblox"


async def test_message_on_unexpected_topic_is_rejected(make):
    h = await make()
    await h.send()
    foreign = MagicMock(topic=f"{ROOT}/pc2/state/foreground_identity", retain=False,
                        payload=raw(h.clock, 50, device="pc1"))
    h.source._message(foreign)
    assert h.current() is None
