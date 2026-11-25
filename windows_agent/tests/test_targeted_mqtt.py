"""Live MQTT v1 single-use capability exchange, no arbitrary kill commands."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt

from gaming_control.mqtt_bridge import Bridge


CONFIG = {"device": {"id": "pc1", "name": "PC 1"},
          "mqtt": {"host": "localhost"}, "games": []}
FOCUS = ("RobloxPlayerBeta.exe", 410, 1000.5, 3, None)


def bridge():
    b = Bridge(CONFIG)
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    b.publish({"in_game": "OFF", "current_game": "idle"}, 123)
    return b


def offer(b, candidate=FOCUS, sample_time=100):
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=101), \
         patch("gaming_control.mqtt_bridge.time.time", return_value=2000):
        context = b.capture_foreground_context()
        assert b.publish_raw_foreground("foreground", candidate, context)
        assert b.publish_target_offer(candidate, context, sample_time=sample_time)
    posts = [c for c in b.client.publish.call_args_list
             if c.args[0] == b.root + "/state/terminate_offer"]
    assert posts
    call = posts[-1]
    assert call.kwargs["qos"] == 0 and call.kwargs["retain"] is False
    assert call.kwargs["properties"].MessageExpiryInterval <= 4
    data = json.loads(call.args[1])
    assert set(data) == {"version", "device_id", "epoch", "sequence",
                         "observed_at", "process", "signature", "token"}
    assert data["device_id"] == "pc1" and data["process"] == FOCUS[0]
    assert "pid" not in data and "path" not in data
    return data


def send(b, data, *, retain=False, topic=None):
    b.on_message(b.client, None, SimpleNamespace(
        topic=topic or b.root + "/command/terminate_target",
        payload=json.dumps(data).encode(), retain=retain))


def request(capability):
    return {"version": 1, "device_id": "pc1", "epoch": capability["epoch"],
            "token": capability["token"], "request_id": "e" * 32}


def test_rules_free_pc_issues_scoped_single_use_token():
    b = bridge()
    assert "terminate_target" in b.command_topics.values()
    assert "terminate_game" not in b.command_topics.values()
    data = offer(b)
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=102):
        send(b, request(data))
        commands = list(b.drain_commands())
    assert len(commands) == 1 and commands[0][0] == "terminate_target"
    assert commands[0][1]["candidate"] == FOCUS
    assert commands[0][1]["sample_time"] == 100
    assert commands[0][1]["received_at"] == 102
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=102):
        send(b, request(data))
        assert list(b.drain_commands()) == []


def test_retain_foreign_expired_and_bad_commands_fail_closed():
    b = bridge()
    data = offer(b)
    cases = [
        (request(data), True, None),
        (request(data) | {"device_id": "pc2"}, False, None),
        (request(data) | {"epoch": "a" * 32}, False, None),
        (request(data) | {"token": "f" * 32}, False, None),
        (request(data) | {"pid": 410}, False, None),
        (request(data), False, "SmartHouse/Gaming/pc2/command/terminate_target"),
    ]
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=102):
        for value, retained, topic in cases:
            send(b, value, retain=retained, topic=topic)
        assert list(b.drain_commands()) == []
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=105.1):
        send(b, request(data))
        assert list(b.drain_commands()) == []


def test_foreground_switch_and_reconnect_revoke_offer():
    b = bridge()
    data = offer(b)
    b.on_disconnect(b.client, None, None, None, None)
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=102):
        send(b, request(data))
        assert list(b.drain_commands()) == []
    b.publish({"in_game": "OFF", "current_game": "idle"}, 125)
    newer = offer(b)
    assert newer["epoch"] != data["epoch"]
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=102):
        context = b.capture_foreground_context()
        assert b.publish_raw_foreground("idle", None, context)
        assert not b.publish_target_offer(None, context, sample_time=None)
        send(b, request(newer))
        assert list(b.drain_commands()) == []


def test_legacy_allowlist_never_enables_targeted_command():
    b = Bridge(CONFIG | {"games": [{"name": "Roblox", "process": "RobloxPlayerBeta.exe"}]})
    assert "terminate_game" in b.command_topics.values()
    assert "terminate_target" not in b.command_topics.values()


def test_unified_offer_matches_actual_published_observation_and_is_one_use():
    """#263: exact v3 epoch, sequence and quantized foreground timestamp."""
    b = bridge()
    focus = SimpleNamespace(foreground_state="foreground", candidate=FOCUS,
                            last_observation_time=100.25)
    policy = {"ac_timeout_seconds": 600, "dc_timeout_seconds": 300,
              "power_source": "ac"}
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=101), \
         patch("gaming_control.mqtt_bridge.time.time", return_value=2000):
        context = b.capture_foreground_context()
        assert b.publish_unified_telemetry(focus, policy, 123)
        assert b.prime_target_receipt(FOCUS, context, sample_time=100.25)
        assert b.publish_target_offer(FOCUS, context, sample_time=100.25)
        assert not b.publish_target_offer(FOCUS, context, sample_time=100.25)
        assert not b.prime_target_receipt(FOCUS, context, sample_time=100.25)
    packets = {call.args[0]: json.loads(call.args[1])
               for call in b.client.publish.call_args_list
               if call.args[0] in (b.root + "/state/telemetry",
                                   b.root + "/state/terminate_offer")}
    snapshot = packets[b.root + "/state/telemetry"]
    capability = packets[b.root + "/state/terminate_offer"]
    assert capability["epoch"] == snapshot["epoch"]
    assert capability["sequence"] == snapshot["sequence"]
    assert capability["observed_at"] == (
        snapshot["observed_at"] - snapshot["foreground"]["sample_age_ms"] / 1000)
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=102):
        send(b, request(capability))
        assert len(list(b.drain_commands())) == 1
        send(b, request(capability))
        assert not list(b.drain_commands())


def test_no_target_offer_after_unknown_or_failed_unified_observation():
    b = bridge()
    policy = {"ac_timeout_seconds": 600, "dc_timeout_seconds": 300,
              "power_source": "ac"}
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=101), \
         patch("gaming_control.mqtt_bridge.time.time", return_value=2000):
        context = b.capture_foreground_context()
        stale = SimpleNamespace(foreground_state="foreground", candidate=FOCUS,
                                last_observation_time=95)
        assert b.publish_unified_telemetry(stale, policy, 123)
        assert not b.prime_target_receipt(FOCUS, context, sample_time=100.25)
        b.client.publish.return_value.rc = mqtt.MQTT_ERR_NO_CONN
        fresh = SimpleNamespace(foreground_state="foreground", candidate=FOCUS,
                                last_observation_time=100.25)
        assert not b.publish_unified_telemetry(fresh, policy, 123)
        assert not b.prime_target_receipt(FOCUS, context, sample_time=100.25)
