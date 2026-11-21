"""Issue #4 raw v2 foreground transport must not rely on Windows game rules."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gaming_control import mqtt_bridge as M
from gaming_control import focus_session as F


@pytest.fixture
def bridge():
    clock = SimpleNamespace(wall=1000.0, mono=100.0)
    client = Mock()
    client.publish.return_value = SimpleNamespace(rc=0)
    config = {"device": {"id": "pc1", "name": "Test PC"},
              "mqtt": {"host": "broker.invalid"},
              "games": [{"name": "Legacy Roblox"}]}
    with patch.object(M.mqtt, "Client", return_value=client), \
            patch.object(M.time, "time", side_effect=lambda: clock.wall), \
            patch.object(M.time, "monotonic", side_effect=lambda: clock.mono):
        b = M.Bridge(config)
        b.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
        b.synced_generation = b.generation
        yield b, client, clock


def snapshots(client):
    return [c for c in client.publish.call_args_list
            if c.args[0].endswith("/state/foreground_identity")]


def test_raw_foreground_process_is_not_chosen_by_windows_rules(bridge):
    b, client, clock = bridge
    context = b.capture_foreground_context()
    assert b.publish_raw_foreground(
        "foreground", ("chrome.exe", 42, 123, 2, None), context)
    sent, = snapshots(client)
    packet = json.loads(sent.args[1])
    assert set(packet) == {"version", "device_id", "epoch", "sequence",
                           "observed_at", "state", "process", "signature"}
    assert packet["version"] == 2
    assert packet["device_id"] == "pc1"
    assert packet["process"] == "chrome.exe"
    assert packet["state"] == "foreground"
    assert packet["signature"] is None
    assert packet["sequence"] == 1
    assert sent.kwargs["qos"] == 0 and sent.kwargs["retain"] is False
    assert 1 <= sent.kwargs["properties"].MessageExpiryInterval <= 10
    assert not any(x in sent.args[1] for x in ("pid", "created", "session", "path", "args"))
    # Raw publication must not consume the old v1 snapshot context.
    assert b.publish_foreground({"active_game": "idle", "gaming_active": "OFF"}, context)
    assert not b.publish_raw_foreground("foreground", ("chrome.exe", 42, 123, 2, None), context)


def test_java_signature_is_sanitized_and_distinguishes_apps(bridge):
    b, client, clock = bridge
    class_name = {"kind": "java_class", "value": "net.minecraft.client.main.Main"}
    assert b.publish_raw_foreground(
        "foreground", ("javaw.exe", 42, 123, 2, class_name),
        b.capture_foreground_context())
    first = json.loads(snapshots(client)[0].args[1])
    assert first["signature"] == class_name
    assert "42" not in first["process"]
    clock.wall += 0.1
    clock.mono += 0.1
    another = {"kind": "java_class", "value": "org.example.other.Main"}
    assert b.publish_raw_foreground(
        "foreground", ("javaw.exe", 99, 124, 2, another),
        b.capture_foreground_context())
    second = json.loads(snapshots(client)[1].args[1])
    assert first["signature"] != second["signature"]
    assert second["sequence"] > first["sequence"]
    assert second["epoch"] == first["epoch"]


def test_unknown_idle_and_unrecognized_java_have_explicit_states(bridge):
    b, client, clock = bridge
    assert b.publish_raw_foreground("idle", None, b.capture_foreground_context())
    clock.wall += 0.1
    clock.mono += 0.1
    assert b.publish_raw_foreground("unknown", None, b.capture_foreground_context())
    clock.wall += 0.1
    clock.mono += 0.1
    assert b.publish_raw_foreground(
        "foreground", ("javaw.exe", 42, 123, 2, None),
        b.capture_foreground_context())
    values = [json.loads(c.args[1]) for c in snapshots(client)]
    assert [v["state"] for v in values] == ["idle", "unknown", "foreground"]
    assert values[0]["process"] is None and values[1]["signature"] is None
    assert values[2]["process"] == "javaw.exe" and values[2]["signature"] is None


@pytest.mark.parametrize("state,candidate", [
    ("foreground", None),
    ("unknown", ("chrome.exe", 42, 123, 2, None)),
    ("idle", ("chrome.exe", 42, 123, 2, None)),
    ("foreground", ("chrome.exe", 42, 123, 2,
                    {"kind": "java_class", "value": "org.example.Main"})),
    ("foreground", ("java.exe", 42, 123, 2,
                    {"kind": "raw", "value": "--password SECRET"})),
    ("playing", None),
])
def test_invalid_raw_identity_is_not_published(bridge, state, candidate):
    b, client, _ = bridge
    assert not b.publish_raw_foreground(state, candidate, b.capture_foreground_context())
    assert not snapshots(client)


def test_raw_snapshot_rejects_stale_or_unsynchronized_context(bridge):
    b, client, clock = bridge
    ctx = b.capture_foreground_context()
    clock.wall += 11
    clock.mono += 11
    assert not b.publish_raw_foreground("idle", None, ctx)
    b.synced_generation = None
    assert not b.publish_raw_foreground("idle", None, b.capture_foreground_context())
    assert not snapshots(client)


def test_raw_snapshot_throttles_but_rotates_epoch_on_reconnect(bridge):
    b, client, clock = bridge
    p = ("chrome.exe", 42, 123, 2, None)
    assert b.publish_raw_foreground("foreground", p, b.capture_foreground_context())
    assert not b.publish_raw_foreground("foreground", p, b.capture_foreground_context())
    clock.wall += 2
    clock.mono += 2
    assert b.publish_raw_foreground("foreground", p, b.capture_foreground_context())
    original = json.loads(snapshots(client)[0].args[1])
    b.on_disconnect(client, None, None, None, None)
    assert not b.publish_raw_foreground("foreground", p, b.capture_foreground_context())
    b.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    b.synced_generation = b.generation
    assert b.publish_raw_foreground("foreground", p, b.capture_foreground_context())
    newer = json.loads(snapshots(client)[2].args[1])
    assert newer["epoch"] != original["epoch"] and newer["sequence"] == 1


@pytest.mark.parametrize("sample,legacy,candidate,expected", [
    ({"time": 10, "status": "window", "pid": 42, "created": 123},
     F.IDLE, ("chrome.exe", 42, 123, 2, None), "foreground"),
    ({"time": 10, "status": "idle"},
     F.IDLE, None, "idle"),
    ({"time": 10, "status": "unknown"},
     F.UNKNOWN, None, "unknown"),
])
def test_focus_probe_raw_state_is_independent_of_legacy_match(
        sample, legacy, candidate, expected):
    probe = F.FocusProbe()
    probe.process = Mock()
    probe.session = 2
    with patch.object(F, "selected_session", return_value=(2, "unlocked")), \
            patch.object(probe, "_report_child_exit", return_value=False), \
            patch.object(probe, "_receive", return_value=sample), \
            patch.object(F, "classify", return_value=legacy), \
            patch.object(F, "candidate_from_sample", return_value=candidate), \
            patch.object(F.time, "monotonic", return_value=10.5):
        assert probe.read([]) == legacy
    assert probe.foreground_state == expected
