"""#176: Windows unified telemetry v3 contract and transport regression tests."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
import pytest

from gaming_control import mqtt_bridge as M
from gaming_control import unified_telemetry as U

EPOCH = "e" * 32
JAVASIG = {"kind": "java_class", "value": "net.minecraft.client.main.Main"}
POLICY = {"ac_timeout_seconds": 600, "dc_timeout_seconds": 300,
          "power_source": "ac"}


class Clock:
    def __init__(self):
        self.mono, self.wall = 100.0, 1790000000.0

    def advance(self, value):
        self.mono += value
        self.wall += value


def focus(clock, *, state="foreground", candidate=None, sample_age=0.1,
          display="on", display_epoch=EPOCH, display_seq=1, event_age=100):
    if candidate is None and state == "foreground":
        candidate = ("RobloxPlayerBeta.exe", 321, 456, 2, None)
    return SimpleNamespace(
        foreground_state=state, candidate=candidate,
        last_observation_time=(clock.mono - sample_age)
                              if sample_age is not None else None,
        display_state=display, display_event_age_ms=event_age,
        display_epoch=display_epoch, display_sequence=display_seq,
        last_input_idle_ms=12000)


@pytest.fixture
def rig():
    clock = Clock()
    client = Mock()
    client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    config = {"device": {"id": "pc1", "name": "Synthetic PC"},
              "mqtt": {"host": "broker.invalid"},
              "telemetry": {"unified_v3_enabled": True},
              "games": [{"name": "Legacy Roblox"}]}
    with patch.object(M.mqtt, "Client", return_value=client), \
         patch.object(M, "installed_version", return_value="0.2.12"), \
         patch.object(M, "installed_build_sha", return_value="f"*40), \
         patch.object(M.time, "monotonic", side_effect=lambda: clock.mono), \
         patch.object(M.time, "time", side_effect=lambda: clock.wall):
        bridge = M.Bridge(config)
        reconnect(bridge)
        yield bridge, client, clock


def reconnect(bridge):
    bridge.on_connect(bridge.client, None, None,
                      SimpleNamespace(is_failure=False), None)
    bridge.synced_generation = bridge.generation


def published(client):
    return [c for c in client.publish.call_args_list
            if c.args[0].endswith("/state/telemetry")]


def payloads(client):
    return [json.loads(c.args[1]) for c in published(client)]


def test_full_v3_snapshot_and_all_agreed_readonly_fields(rig):
    bridge, client, clock = rig
    assert bridge.metadata["unified_telemetry_protocol"] == 3
    assert bridge.publish_unified_telemetry(focus(clock), POLICY, 45630)
    calls = published(client)
    assert len(calls) == 1
    call = calls[0]
    assert call.args[0] == "SmartHouse/Gaming/pc1/state/telemetry"
    assert call.kwargs["qos"] == 0 and call.kwargs["retain"] is False
    assert call.kwargs["properties"].MessageExpiryInterval == 6
    assert len(call.args[1].encode("utf8")) <= 4096
    packet, = payloads(client)
    assert set(packet) == {"version", "device_id", "epoch", "sequence",
                           "observed_at", "foreground", "display", "system"}
    assert packet["version"] == 3 and packet["device_id"] == "pc1"
    assert len(packet["epoch"]) == 32 and packet["sequence"] == 1
    assert packet["observed_at"] == clock.wall
    assert packet["foreground"] == {
        "state": "foreground", "process": "RobloxPlayerBeta.exe",
        "signature": None, "sample_age_ms": 99,
    } or packet["foreground"] == {
        "state": "foreground", "process": "RobloxPlayerBeta.exe",
        "signature": None, "sample_age_ms": 100,
    }
    display = packet["display"]
    assert set(display) == {"state", "scope", "event_epoch",
                            "event_sequence", "event_age_ms", "sample_age_ms",
                            "ac_timeout_seconds", "dc_timeout_seconds",
                            "power_source", "last_input_idle_ms"}
    assert display["state"] == "on" and display["scope"] == "windows_console"
    assert display["event_epoch"] == EPOCH and display["event_sequence"] == 1
    assert display["event_age_ms"] in (199, 200)
    assert display["ac_timeout_seconds"] == 600
    assert display["dc_timeout_seconds"] == 300
    assert display["power_source"] == "ac"
    assert display["last_input_idle_ms"] in (12099, 12100)
    assert packet["system"] == {
        "uptime_seconds": 45630, "agent_version": "0.2.12",
        "agent_build_sha": "f"*40}
    assert not any(key in call.args[1] for key in (
        '"pid"', '"username"', '"window_title"', '"cmdline"',
        '"password"', '"token"', '"path"', '"command"', '"ota"'))


def test_periodic_full_refresh_and_immediate_events(rig):
    bridge, client, clock = rig
    old = focus(clock)
    assert bridge.publish_unified_telemetry(old, POLICY, 12)
    clock.advance(0.5)
    assert not bridge.publish_unified_telemetry(focus(clock), POLICY, 13)
    clock.advance(0.1)
    assert bridge.publish_unified_telemetry(
        focus(clock, display="off", display_seq=2), POLICY, 13)
    clock.advance(0.1)
    assert bridge.publish_unified_telemetry(
        focus(clock, state="idle", candidate=None,
              display="off", display_seq=2), POLICY, 13)
    clock.advance(0.1)
    assert bridge.publish_unified_telemetry(
        focus(clock, state="unknown", candidate=None,
              display="off", display_seq=2), POLICY, 13)
    clock.advance(2.1)
    assert bridge.publish_unified_telemetry(
        focus(clock, state="unknown", candidate=None,
              display="off", display_seq=2), POLICY, 15)
    packets = payloads(client)
    assert [p["sequence"] for p in packets] == [1, 2, 3, 4, 5]
    assert [p["foreground"]["state"] for p in packets] == [
        "foreground", "foreground", "idle", "unknown", "unknown"]
    assert all(set(p) == set(packets[0]) for p in packets)
    assert packets[1]["display"]["state"] == "off"
    assert packets[-1]["system"]["uptime_seconds"] == 15


def test_same_executable_focus_switch_is_an_immediate_transition(rig):
    bridge, client, clock = rig
    assert bridge.publish_unified_telemetry(focus(clock), POLICY, 10)
    clock.advance(.2)
    candidate = ("RobloxPlayerBeta.exe", 322, 458, 2, None)
    assert bridge.publish_unified_telemetry(
        focus(clock, candidate=candidate), POLICY, 11)
    first, second = payloads(client)
    assert first["foreground"] == second["foreground"]
    assert first["sequence"] + 1 == second["sequence"]
    assert "pid" not in second["foreground"]  # Never expose private PID.
    assert set(second["foreground"]) == {"state", "process", "signature", "sample_age_ms"}


def test_java_discriminator_survives_without_argv_pid_or_path(rig):
    bridge, client, clock = rig
    entry = ("javaw.exe", 333, 999, 2, JAVASIG)
    assert bridge.publish_unified_telemetry(
        focus(clock, candidate=entry), POLICY, 10)
    one, = payloads(client)
    assert one["foreground"]["signature"] == JAVASIG
    clock.advance(0.1)
    another = ("javaw.exe", 334, 1000, 2,
               {"kind": "java_class", "value": "org.example.Other.Main"})
    assert bridge.publish_unified_telemetry(
        focus(clock, candidate=another), POLICY, 11)
    assert payloads(client)[1]["foreground"]["signature"] != JAVASIG
    clock.advance(0.1)
    assert bridge.publish_unified_telemetry(
        focus(clock, candidate=("javaw.exe", 335, 1001, 2, None)),
        POLICY, 12)
    assert payloads(client)[2]["foreground"]["state"] == "foreground"
    assert payloads(client)[2]["foreground"]["signature"] is None


@pytest.mark.parametrize("state,sample_age,candidate,expected", [
    ("idle", 0.1, None, "idle"),
    ("idle", None, None, "unknown"),
    ("idle", 10, None, "unknown"),
    ("foreground", None, ("RobloxPlayerBeta.exe", 42, 123, 2, None), "unknown"),
    ("foreground", 10, ("RobloxPlayerBeta.exe", 42, 123, 2, None), "unknown"),
    ("foreground", .1, None, "foreground"),  # focus() supplies candidate
    ("unknown", .1, None, "unknown"),
    ("foreground", .1, ("evil.exe", 42, 123, 2,
                       {"kind": "java_class", "value": "org.example.Main"}), "unknown"),
])
def test_unavailable_helper_and_malformed_identity_fail_to_unknown(
        rig, state, sample_age, candidate, expected):
    bridge, client, clock = rig
    sample = focus(clock, state=state, candidate=candidate,
                   sample_age=sample_age)
    assert bridge.publish_unified_telemetry(sample, POLICY, 10)
    assert payloads(client)[0]["foreground"]["state"] == expected
    if expected == "unknown":
        assert payloads(client)[0]["foreground"]["sample_age_ms"] is None
        assert payloads(client)[0]["foreground"]["process"] is None


def test_expired_display_evidence_never_claims_off(rig):
    bridge, client, clock = rig
    sample = focus(clock, display="off", sample_age=4)
    assert bridge.publish_unified_telemetry(sample, POLICY, 10)
    packet, = payloads(client)
    assert packet["display"]["state"] == "unknown"
    assert packet["display"]["sample_age_ms"] is None
    assert packet["display"]["event_age_ms"] is None
    assert packet["display"]["event_epoch"] is None
    assert packet["display"]["last_input_idle_ms"] is None
    assert packet["foreground"]["state"] == "unknown"


@pytest.mark.parametrize("value", [
    {"display_epoch": "bad"}, {"display_sequence": 0},
    {"display_event_age_ms": -1}, {"display_state": "OFF"},
    {"display_event_age_ms": True},
])
def test_bad_display_receipt_is_unknown_without_bonus(rig, value):
    bridge, client, clock = rig
    sample = focus(clock, display="off")
    sample.__dict__.update(value)
    assert bridge.publish_unified_telemetry(sample, POLICY, 10)
    packet, = payloads(client)
    assert packet["display"]["state"] == "unknown"
    assert packet["display"]["event_epoch"] is None
    assert packet["display"]["event_sequence"] is None
    assert "bonus" not in client.publish.call_args.args[1]


def test_bad_policy_is_null_and_does_not_break_raw_activity(rig):
    bridge, client, clock = rig
    assert bridge.publish_unified_telemetry(
        focus(clock), {"ac_timeout_seconds": -1}, 10)
    row, = payloads(client)
    assert row["display"]["ac_timeout_seconds"] is None
    assert row["display"]["power_source"] == "unknown"
    assert row["foreground"]["state"] == "foreground"


def test_reconnect_rotates_epoch_requires_resync_no_replay(rig):
    bridge, client, clock = rig
    assert bridge.publish_unified_telemetry(focus(clock), POLICY, 20)
    first, = payloads(client)
    bridge.on_disconnect(client, None, None, None, None)
    assert not bridge.publish_unified_telemetry(focus(clock), POLICY, 20)
    clock.advance(1)
    bridge.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    assert not bridge.publish_unified_telemetry(focus(clock), POLICY, 21)
    bridge.synced_generation = bridge.generation
    assert bridge.publish_unified_telemetry(focus(clock), POLICY, 21)
    second = payloads(client)[1]
    assert first["epoch"] != second["epoch"]
    assert second["sequence"] == 1 and second["observed_at"] > first["observed_at"]


def test_transport_failure_never_republishes_old_snapshot(rig):
    bridge, client, clock = rig
    client.publish.return_value = SimpleNamespace(rc=4)
    assert not bridge.publish_unified_telemetry(focus(clock), POLICY, 10)
    clock.advance(.25)
    client.publish.return_value = SimpleNamespace(rc=0)
    assert bridge.publish_unified_telemetry(
        focus(clock, state="idle", candidate=None), POLICY, 11)
    rows = payloads(client)
    assert rows[0]["sequence"] == 1 and rows[1]["sequence"] == 2
    assert rows[1]["foreground"]["state"] == "idle"


def test_time_anomaly_prevents_reordered_timestamp(rig):
    bridge, client, clock = rig
    assert bridge.publish_unified_telemetry(focus(clock), POLICY, 10)
    clock.mono += 1
    clock.wall -= 20
    assert not bridge.publish_unified_telemetry(focus(clock), POLICY, 11)
    assert len(payloads(client)) == 1


def test_inflight_disconnect_disallows_stale_session_commit(rig):
    bridge, client, clock = rig

    def race(*args, **kwargs):
        bridge.on_disconnect(client, None, None, None, None)
        return SimpleNamespace(rc=0)

    client.publish.side_effect = race
    assert not bridge.publish_unified_telemetry(focus(clock), POLICY, 10)
    client.publish.side_effect = None
    clock.advance(1)
    reconnect(bridge)
    assert bridge.publish_unified_telemetry(focus(clock), POLICY, 11)
    first, second = payloads(client)
    assert first["epoch"] != second["epoch"]
    assert second["sequence"] == 1


def test_v3_is_mandatory_and_explicit_legacy_disable_is_rejected():
    config = {"device": {"id": "pc1", "name": "Test"},
              "mqtt": {"host": "broker.invalid"}, "games": []}
    with patch.object(M, "installed_version", return_value="0.3.0"):
        mandatory = M.Bridge(config)
        assert mandatory.unified_enabled is True
        assert mandatory.metadata["unified_telemetry_protocol"] == 3
        assert not mandatory.publish_unified_telemetry(
            SimpleNamespace(), POLICY, 10)  # cannot publish offline
        for value in ("false", False, 0, None):
            with pytest.raises(ValueError):
                M.Bridge(config | {"telemetry": {"unified_v3_enabled": value}})
        with pytest.raises(ValueError):
            M.Bridge(config | {"device": {"id": "p" * 65,
                                        "name": "Oversize"}})


def test_two_pcs_scoped_topics_and_epochs(rig):
    first, client, clock = rig
    assert first.publish_unified_telemetry(focus(clock), POLICY, 10)
    config = {"device": {"id": "pc2", "name": "Other"},
              "mqtt": {"host": "broker.invalid"},
              "telemetry": {"unified_v3_enabled": True}, "games": []}
    other = M.Bridge(config)
    reconnect(other)
    assert other.publish_unified_telemetry(focus(clock), POLICY, 10)
    calls = published(client)
    assert calls[0].args[0] != calls[1].args[0]
    assert payloads(client)[0]["device_id"] == "pc1"
    assert payloads(client)[1]["device_id"] == "pc2"
    assert payloads(client)[0]["epoch"] != payloads(client)[1]["epoch"]


def test_envelope_and_size_limits_are_explicit():
    fg = U.foreground_fields("unknown", None, None)
    display = U.display_fields(SimpleNamespace(), POLICY, 100)
    system = U.system_fields(10, "0.2.12", None)
    snapshot = U.make_snapshot("pc1", "a" * 32, 1, 1790000000, fg, display, system)
    assert len(snapshot) <= U.MAX_BYTES
    for args in [
        ("bad id!", "a"*32, 1, 1790000000),
        ("pc1", "invalid", 1, 1790000000),
        ("pc1", "a"*32, True, 1790000000),
        ("pc1", "a"*32, 0, 1790000000),
        ("pc1", "a"*32, 1, float("nan")),
    ]:
        with pytest.raises(ValueError):
            U.make_snapshot(*args, fg, display, system)
    with pytest.raises(ValueError):
        U.make_snapshot("pc1", "a"*32, 2, 1790000000, fg, display,
                        system | {"junk": "A" * 5000})


def test_system_unknown_fields_are_not_fabricated():
    assert U.system_fields(1, "0.2.12", "broken")["agent_build_sha"] is None
    for value in (-1, None, 1.4, True):
        with pytest.raises(ValueError):
            U.system_fields(value, "0.2.12", None)
    with pytest.raises(ValueError):
        U.system_fields(12, "dev-unsafe", None)


def test_clean_cut_rejects_untrusted_device_identifier_early():
    cfg = {"device": {"id": "bad id!", "name": "Untrusted"},
           "mqtt": {"host": "localhost"}, "games": []}
    with pytest.raises(ValueError, match="Invalid device id"):
        M.Bridge(cfg)


def test_no_authenticated_sample_context_after_broker_disconnect():
    cfg = {"device": {"id": "pc1", "name": "Test"},
           "mqtt": {"host": "localhost"}, "games": []}
    bridge = M.Bridge(cfg)
    bridge.client = Mock()
    bridge.on_connect(bridge.client, None, None,
                      SimpleNamespace(is_failure=False), None)
    assert bridge.capture_foreground_context() is not None
    bridge.on_disconnect(bridge.client, None, None, None, None)
    assert bridge.capture_foreground_context() is None
