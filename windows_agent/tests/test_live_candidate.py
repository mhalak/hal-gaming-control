"""Live application candidate must be safe, fresh and advisory only."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gaming_control import mqtt_bridge as M
from gaming_control.foreground import candidate_from_sample


SAMPLE = {"time": 10, "status": "window", "pid": 42, "created": 123}


def process(name="chrome.exe"):
    p = Mock()
    p.name.return_value = name
    p.create_time.return_value = 123
    p.is_running.return_value = True
    return p


def capture(sample=SAMPLE, *, name="chrome.exe", session=2, now=10.5):
    return candidate_from_sample(sample, session, now,
                                 process_factory=lambda pid: process(name),
                                 session_lookup=lambda pid: 2)


def test_untracked_browser_is_detectable_without_rule_or_path():
    assert capture() == ("chrome.exe", 42, 123, 2, None)
    assert capture(name="javaw.exe") == ("javaw.exe", 42, 123, 2, None)


@pytest.mark.parametrize("sample", [
    SAMPLE | {"status": "idle"}, SAMPLE | {"time": 7},
    SAMPLE | {"pid": True}, SAMPLE | {"created": 122},
    SAMPLE | {"status": "unknown"}, SAMPLE | {"pid": -1},
])
def test_invalid_or_stale_focus_is_not_an_enrollment_candidate(sample):
    assert capture(sample=sample) is None


@pytest.mark.parametrize("name", ["private/path.exe", r"C:\\folder\\game.exe",
                                   "test\\n.exe", "bad.exe" * 30])
def test_candidate_process_identity_is_basename_only(name):
    assert capture(name=name) is None


def test_other_user_session_is_not_a_candidate():
    assert capture(session=3) is None


@pytest.fixture
def bridge():
    clock = SimpleNamespace(wall=1000.0, mono=100.0)
    client = Mock()
    client.publish.return_value = SimpleNamespace(rc=0)
    config = {"device": {"id": "pc1", "name": "Synthetic PC"},
              "mqtt": {"host": "broker.invalid"}, "games": [{"name": "Roblox"}]}
    with patch.object(M.mqtt, "Client", return_value=client), \
            patch.object(M, "installed_version", return_value="0.2.4"), \
            patch.object(M.time, "time", side_effect=lambda: clock.wall), \
            patch.object(M.time, "monotonic", side_effect=lambda: clock.mono):
        b = M.Bridge(config)
        b.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
        b.synced_generation = b.generation
        yield b, client, clock


def candidates(client):
    return [c for c in client.publish.call_args_list
            if c.args[0].endswith("/state/foreground_candidate")]


def test_candidate_publisher_does_not_leak_identity_or_retain(bridge):
    b, client, clock = bridge
    assert b.publish_candidate(("chrome.exe", 42, 123, 2))
    call, = candidates(client)
    value = json.loads(call.args[1])
    assert set(value) == {"version", "device_id", "process", "signature", "token", "observed_at"}
    assert value["process"] == "chrome.exe"
    assert value["device_id"] == "pc1"
    assert len(value["token"]) == 32
    assert call.kwargs["retain"] is False
    assert call.kwargs["qos"] == 0
    assert call.kwargs["properties"].MessageExpiryInterval == M.CANDIDATE_EXPIRY
    assert "pid" not in value and "created" not in value and "session" not in value
    assert not b.publish_candidate(("chrome.exe", 42, 123, 2))
    clock.wall += 2
    clock.mono += 2
    assert b.publish_candidate(("chrome.exe", 42, 123, 2))
    assert json.loads(candidates(client)[1].args[1])["token"] == value["token"]
    assert b.publish_candidate(None) is False


def test_candidate_token_rotates_on_focus_change_and_reconnect(bridge):
    b, client, clock = bridge
    b.publish_candidate(("chrome.exe", 42, 123, 2))
    first = json.loads(candidates(client)[0].args[1])["token"]
    clock.wall += 0.1
    clock.mono += 0.1
    assert b.publish_candidate(("notepad.exe", 43, 125, 2, None))
    second = json.loads(candidates(client)[1].args[1])["token"]
    assert first != second
    b.on_disconnect(client, None, None, None, None)
    assert not b.publish_candidate(("notepad.exe", 43, 125, 2))
    b.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    b.synced_generation = b.generation
    assert b.publish_candidate(("notepad.exe", 43, 125, 2))
    assert json.loads(candidates(client)[2].args[1])["token"] != second


def test_unknown_and_unsynchronized_candidate_never_publish(bridge):
    b, client, _ = bridge
    b.synced_generation = None
    assert not b.publish_candidate(("chrome.exe", 42, 123, 2))
    b.synced_generation = b.generation
    assert not b.publish_candidate(None)
    assert not candidates(client)
