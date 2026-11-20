"""Atomic foreground publisher contract; mocked broker and deterministic clocks."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gaming_control import mqtt_bridge as M


GAME = {"active_game": "Roblox", "gaming_active": "ON"}
IDLE = {"active_game": "idle", "gaming_active": "OFF"}
UNKNOWN = {"active_game": "unknown", "gaming_active": "UNKNOWN"}


@pytest.fixture
def rig():
    clock = SimpleNamespace(wall=1000.0, mono=100.0)
    client = Mock()
    client.publish.return_value = SimpleNamespace(rc=0)
    config = {"device": {"id": "pc1", "name": "Synthetic PC"},
              "mqtt": {"host": "broker.invalid"},
              "games": [{"name": "Roblox"}, {"name": "Minecraft"}]}
    with patch.object(M.mqtt, "Client", return_value=client), \
            patch.object(M, "installed_version", return_value="1.2.3"), \
            patch.object(M.time, "time", side_effect=lambda: clock.wall), \
            patch.object(M.time, "monotonic", side_effect=lambda: clock.mono):
        bridge = M.Bridge(config)
        reconnect(bridge)
        yield bridge, client, clock


def reconnect(bridge):
    bridge.on_connect(bridge.client, None, None,
                      SimpleNamespace(is_failure=False), None)
    bridge.synced_generation = bridge.generation


def disconnect(bridge):
    bridge.on_disconnect(bridge.client, None, None, None, None)


def advance(clock, seconds):
    clock.wall += seconds
    clock.mono += seconds


def send(bridge, values):
    return bridge.publish_foreground(values, bridge.capture_foreground_context())


def packets(client):
    result = []
    for call in client.publish.call_args_list:
        topic, raw = call.args
        if topic.endswith("/state/foreground_snapshot"):
            assert topic == "SmartHouse/Gaming/pc1/state/foreground_snapshot"
            assert call.kwargs["retain"] is False
            assert call.kwargs["qos"] == 0
            assert call.kwargs["properties"].MessageExpiryInterval <= 10
            result.append(json.loads(raw))
    return result


def test_foreground_publisher_atomic_schema(rig):
    bridge, client, clock = rig
    assert send(bridge, GAME)
    packet, = packets(client)
    assert packet == {"version": 1, "device_id": "pc1", "epoch": packet["epoch"],
                      "sequence": 1, "observed_at": clock.wall, **GAME}
    assert len(packet["epoch"]) == 32
    int(packet["epoch"], 16)


def test_foreground_publisher_periodic_and_immediate_state_change(rig):
    bridge, client, clock = rig
    assert send(bridge, GAME)
    advance(clock, 1)
    send(bridge, GAME)
    assert len(packets(client)) == 1
    assert send(bridge, IDLE)
    advance(clock, 2)
    assert send(bridge, IDLE)
    advance(clock, 0.1)
    assert send(bridge, UNKNOWN)
    assert [p["sequence"] for p in packets(client)] == [1, 2, 3, 4]
    assert [p["active_game"] for p in packets(client)] == ["Roblox", "idle", "idle", "unknown"]


def test_foreground_publisher_reconnect_requires_new_observation(rig):
    bridge, client, clock = rig
    assert send(bridge, GAME)
    stale = bridge.capture_foreground_context()
    old_epoch = packets(client)[0]["epoch"]
    disconnect(bridge)
    assert bridge.capture_foreground_context() is None
    advance(clock, 1)
    reconnect(bridge)
    assert not bridge.publish_foreground(GAME, stale)
    assert send(bridge, IDLE)
    first, second = packets(client)
    assert second["sequence"] == 1 and second["epoch"] != old_epoch
    assert first["epoch"] == old_epoch
    assert second["active_game"] == "idle"


def test_foreground_publisher_requires_synchronized_connection(rig):
    bridge, client, _ = rig
    bridge.synced_generation = None
    assert not send(bridge, GAME)
    assert packets(client) == []
    disconnect(bridge)
    assert not send(bridge, GAME)
    assert packets(client) == []


@pytest.mark.parametrize("delay", [10, 11, -1])
def test_foreground_publisher_rejects_expired_or_regressed_capture(rig, delay):
    bridge, client, clock = rig
    context = bridge.capture_foreground_context()
    advance(clock, delay)
    assert not bridge.publish_foreground(GAME, context)
    assert packets(client) == []


def test_foreground_publisher_uses_capture_not_delivery_timestamp(rig):
    bridge, client, clock = rig
    context = bridge.capture_foreground_context()
    captured = clock.wall
    advance(clock, 3)
    assert bridge.publish_foreground(GAME, context)
    packet, = packets(client)
    assert packet["observed_at"] == captured
    assert client.publish.call_args.kwargs["properties"].MessageExpiryInterval <= 7


@pytest.mark.parametrize("values", [
    {}, {"active_game": "Chrome", "gaming_active": "ON"},
    {"active_game": "Roblox", "gaming_active": "OFF"},
    {"active_game": "Roblox | Minecraft", "gaming_active": "ON"},
    {"active_game": [], "gaming_active": "ON"},
])
def test_foreground_publisher_invalid_pair_is_explicit_unknown(rig, values):
    bridge, client, _ = rig
    assert send(bridge, values)
    packet, = packets(client)
    assert {k: packet[k] for k in UNKNOWN} == UNKNOWN


def test_foreground_publisher_never_exposes_process_metadata(rig):
    bridge, client, _ = rig
    assert send(bridge, GAME | {"pid": 12, "cmdline": "synthetic secret",
                               "window_title": "synthetic private"})
    packet, = packets(client)
    assert set(packet) == {"version", "device_id", "epoch", "sequence",
                           "observed_at", "active_game", "gaming_active"}


def test_foreground_publisher_failed_send_does_not_replay_packet(rig):
    bridge, client, clock = rig
    client.publish.return_value = SimpleNamespace(rc=4)
    assert not send(bridge, GAME)
    advance(clock, 1)
    client.publish.return_value = SimpleNamespace(rc=0)
    assert send(bridge, IDLE)
    first, second = packets(client)
    assert second["sequence"] > first["sequence"]
    assert second["active_game"] == "idle"
    assert second["observed_at"] > first["observed_at"]


def test_foreground_publisher_distinct_bridge_epochs(rig):
    bridge, client, _ = rig
    assert send(bridge, GAME)
    config = {"device": {"id": "pc1", "name": "Synthetic PC"},
              "mqtt": {"host": "broker.invalid"}, "games": [{"name": "Roblox"}]}
    other = M.Bridge(config)
    reconnect(other)
    assert send(other, GAME)
    first, second = packets(client)
    assert first["epoch"] != second["epoch"]
