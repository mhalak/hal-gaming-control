from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
import paho.mqtt.client as mqtt
from gaming_control.mqtt_bridge import Bridge

CONFIG = {'device': {'id': 'pc1', 'name': 'PC 1'}, 'mqtt': {'host': 'localhost'},
          'games': [{'name': 'Game', 'process': 'game.exe'}]}


def connected_bridge():
    b = Bridge(CONFIG)
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    return b


def send(b, command='lock_pc', payload=b'PRESS', retain=False):
    b.on_message(b.client, None, SimpleNamespace(topic=b.root + '/command/' + command,
                                                payload=payload, retain=retain))


def test_only_explicit_valid_commands():
    b = connected_bridge()
    send(b, retain=True)
    send(b, payload=b'ON')
    send(b, command='reset')
    send(b)
    assert list(b.drain_commands()) == ['lock_pc']
    for call in b.client.subscribe.call_args_list[:2]:
        assert call.kwargs['options'].retainAsPublished
        assert call.kwargs['options'].retainHandling == 2


def test_no_actions_after_reconnect():
    b = connected_bridge()
    send(b)
    b.on_disconnect(b.client, None, None, None, None)
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert list(b.drain_commands()) == []
    send(b, command='terminate_game')
    assert list(b.drain_commands()) == ['terminate_game']


def test_stale_actions_discarded():
    b = connected_bridge()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=1):
        send(b)
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=12):
        assert list(b.drain_commands()) == []


def test_clean_cut_one_uptime_json_source_and_no_old_scalar_publish():
    b = connected_bridge()
    assert b.publish({'in_game': 'ON', 'current_game': 'Roblox'}, 100)
    calls = b.client.publish.call_args_list
    tombstones = {c.args[0] for c in calls if len(c.args) > 1
                  and c.args[1] == b'' and '/state/' in c.args[0]}
    expected = {b.root + '/state/' + key
                for key in ('uptime', 'in_game', 'current_game',
                            'gaming_active', 'active_game',
                            'focus_availability')}
    assert tombstones == expected
    assert all(c.kwargs == {'qos': 1, 'retain': True}
               for c in calls if c.args[0] in expected)
    assert not any(c.args[0] in expected and c.args[1] not in (b'',)
                   for c in calls)
    uptime = b.configs[
        'homeassistant/sensor/smarthouse_gaming_pc1_uptime/config']
    assert uptime['state_topic'] == b.root + '/state/telemetry'
    assert 'value_json.system.uptime_seconds' in uptime['value_template']
    assert uptime['unique_id'] == 'smarthouse_gaming_pc1_uptime'
    assert b.synced_generation == b.generation


def test_clean_cut_reconnect_resyncs_without_old_retained_state():
    b = connected_bridge()
    assert b.publish({}, 10)
    b.on_disconnect(b.client, None, None, None, None)
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    b.client.publish.reset_mock()
    assert b.publish({}, 11)
    calls = b.client.publish.call_args_list
    assert any(c.args[:2] == (b.root + '/availability', 'online') for c in calls)
    assert all(c.args[1] == b'' for c in calls
               if c.args[0].endswith('/state/uptime'))
    assert b.synced_generation == b.generation


def test_versioned_custom_discovery():
    import json
    b = connected_bridge()
    b.publish({'in_game': 'OFF', 'current_game': 'idle'}, 100)
    calls = [c for c in b.client.publish.call_args_list if c.args[0] == b.root + '/discovery']
    assert len(calls) == 1 and calls[0].kwargs['retain']
    data = json.loads(calls[0].args[1])
    assert data['protocol_version'] == 1 and data['device_id'] == 'pc1'
    assert data['actions'] == ['terminate_game', 'lock_pc']


def test_startup_requires_offline_then_exact_tombstones_then_online():
    b = connected_bridge()
    assert b.publish({'gaming_active': 'ON', 'active_game': 'Roblox'}, 12)
    calls = [c for c in b.client.publish.call_args_list
             if c.args[0] == b.root + '/availability']
    assert [c.args[1] for c in calls] == ['offline', 'online']
    assert all(c.kwargs == {'qos': 1, 'retain': True} for c in calls)
    assert b.metadata['unified_telemetry_protocol'] == 3
    assert b.synced_generation == b.generation


def test_missing_legacy_tombstone_ack_fails_closed_before_online():
    b = connected_bridge()
    ack = b.client.publish.return_value
    lost = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    lost.is_published.return_value = False
    b.client.publish.side_effect = (
        lambda topic, *args, **kwargs: lost
        if topic == b.root + '/state/uptime' else ack)
    assert not b.publish({'in_game': 'ON'}, 12)
    assert b.synced_generation is None
    assert b.refresh_requested
    assert not any(c.args[:2] == (b.root + '/availability', 'online')
                   for c in b.client.publish.call_args_list)
    b.client.publish.side_effect = None
    assert b.publish({}, 13)
    assert b.synced_generation == b.generation


def test_online_ack_required_before_synchronized_v3_publish():
    b = connected_bridge()
    ack = b.client.publish.return_value
    lost = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    lost.is_published.return_value = False
    b.client.publish.side_effect = (
        lambda topic, value, **kwargs: lost
        if (topic, value) == (b.root + '/availability', 'online') else ack)
    assert not b.publish({}, 12)
    assert b.synced_generation is None
    assert b.refresh_requested
    assert b.client.publish.call_args.args[:2] == (b.root + '/availability', 'offline')
    b.client.publish.side_effect = None
    assert b.publish({}, 13)


def test_disconnect_during_cleanup_never_announces_online():
    b = connected_bridge()
    ack = b.client.publish.return_value
    def deliver(topic, *args, **kwargs):
        if topic == b.root + '/state/uptime':
            b.on_disconnect(b.client, None, None, None, None)
        return ack
    b.client.publish.side_effect = deliver
    assert not b.publish({}, 12)
    assert b.synced_generation is None
    assert not any(c.args[:2] == (b.root + '/availability', 'online')
                   for c in b.client.publish.call_args_list)


def test_disconnected_publish_never_sends_telemetry():
    b = connected_bridge()
    b.on_disconnect(b.client, None, None, None, None)
    b.client.publish.reset_mock()
    assert not b.publish({'gaming_active': 'ON', 'active_game': 'Roblox'}, 12)
    b.client.publish.assert_not_called()
    assert b.synced_generation is None
    assert b.refresh_requested


def test_unchanged_v3_sync_does_not_republish_old_scalar_states():
    b = connected_bridge()
    assert b.publish({'gaming_active': 'ON', 'active_game': 'Roblox'}, 12)
    b.client.publish.reset_mock()
    assert b.publish({'gaming_active': 'OFF', 'active_game': 'idle'}, 13)
    b.client.publish.assert_not_called()


def test_home_assistant_restart_refreshes_same_uptime_discovery():
    b = connected_bridge()
    assert b.publish({}, 12)
    b.on_message(b.client, None, SimpleNamespace(
        topic=b.prefix + '/status', payload=b'online'))
    b.client.publish.reset_mock()
    assert b.publish({}, 13)
    assert any(c.args[0] == b.root + '/discovery'
               for c in b.client.publish.call_args_list)
    assert not any(c.args[0] == b.root + '/state/telemetry'
                   for c in b.client.publish.call_args_list)
    assert b.synced_generation == b.generation


def test_failed_online_ack_does_not_commit_snapshot():
    b = connected_bridge()
    ack = b.client.publish.return_value
    lost = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    lost.is_published.return_value = False
    b.client.publish.side_effect = (
        lambda topic, value, **kwargs: lost
        if (topic, value) == (b.root + '/availability', 'online') else ack
    )
    assert not b.publish({'gaming_active': 'ON', 'active_game': 'Roblox'}, 12)
    assert b.synced_generation is None
    assert not b.last
    assert b.refresh_requested
    assert b.client.publish.call_args.args[:2] == (b.root + '/availability', 'offline')
    b.client.publish.side_effect = None
    assert b.publish({'gaming_active': 'OFF', 'active_game': 'idle'}, 13)
    assert b.synced_generation == b.generation


def test_failed_initial_offline_ack_stops_before_discovery():
    b = connected_bridge()
    b.client.publish.return_value.is_published.return_value = False
    assert not b.publish({'gaming_active': 'ON', 'active_game': 'Roblox'}, 12)
    assert [c.args[:2] for c in b.client.publish.call_args_list] == [
        (b.root + '/availability', 'offline'),
        (b.root + '/availability', 'offline'),
    ]
    assert b.synced_generation is None
    assert b.refresh_requested


def test_v2_agent_retired_activity_discovery_is_exact_and_never_readvertised():
    b = connected_bridge()
    b._refresh_discovery()
    calls = b.client.publish.call_args_list
    tombstones = {c.args[0] for c in calls if len(c.args) > 1 and c.args[1] == b''}
    keep = {c.args[0] for c in calls if c.args[0] in b.configs}
    assert len(b.configs) == 3
    assert keep == set(b.configs)
    expected = {
        f'{b.prefix}/sensor/smarthouse_gaming_pc1_current_game/config',
        f'{b.prefix}/sensor/smarthouse_gaming_pc1_active_game/config',
        f'{b.prefix}/binary_sensor/smarthouse_gaming_pc1_in_game/config',
        f'{b.prefix}/binary_sensor/smarthouse_gaming_pc1_gaming_active/config',
    }
    assert expected <= tombstones
    assert tombstones.isdisjoint(keep)
    assert all('pc2' not in topic and '#' not in topic and '+' not in topic
               for topic in tombstones)
    assert all(c.kwargs == {'qos': 1, 'retain': True}
               for c in calls if c.args[0] in expected)
    assert any(topic.endswith('_terminate_game/config') for topic in keep)
    assert any(topic.endswith('_lock_pc/config') for topic in keep)
    assert any(topic.endswith('_uptime/config') for topic in keep)


def test_no_rules_do_not_accept_terminate_and_retract_native_button():
    import json
    cfg = {**CONFIG, "games": []}
    b = Bridge(cfg)
    assert "terminate_game" not in b.command_topics.values()
    assert set(b.command_topics.values()) == {"lock_pc", "terminate_target"}
    assert b.metadata["actions"] == ["lock_pc"]
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    send(b, command="terminate_game")
    assert list(b.drain_commands()) == []
    assert b.publish({"in_game": "OFF", "current_game": "idle"}, 100)
    topic = f"{b.prefix}/button/smarthouse_gaming_pc1_terminate_game/config"
    tombstones = [c for c in b.client.publish.call_args_list if c.args[:2] == (topic, b"")]
    assert len(tombstones) == 1
    assert tombstones[0].kwargs == {"qos": 1, "retain": True}
    assert topic not in b.configs
    discovery_messages = [c for c in b.client.publish.call_args_list
                          if c.args[0] == b.root + "/discovery"]
    assert json.loads(discovery_messages[-1].args[1])["actions"] == ["lock_pc"]
    assert all("pc2" not in c.args[0] for c in b.client.publish.call_args_list)


POLICY = {"ac_timeout_seconds": 600, "dc_timeout_seconds": 300,
          "power_source": "ac"}


@contextmanager
def pinned_clock(mono):
    with patch("gaming_control.mqtt_bridge.time.monotonic", return_value=mono), \
         patch("gaming_control.mqtt_bridge.time.time", return_value=2000 + mono):
        yield


def observe_v3(b, candidate, sample_time, *, mono):
    """Publish one real v3 observation under a pinned, deterministic clock.

    A target receipt may only be primed from an observation that was actually
    published, so the tests must not depend on the runner's absolute
    time.monotonic() (a fresh CI runner can be seconds old)."""
    focus = SimpleNamespace(foreground_state="foreground", candidate=candidate,
                            last_observation_time=sample_time)
    with pinned_clock(mono):
        context = b.capture_foreground_context()
        assert b.publish_unified_telemetry(focus, POLICY, 123)
    return context


def test_target_offer_is_based_on_private_v3_receipt_not_old_raw_topic():
    b = Bridge({**CONFIG, "games": []})
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.publish({}, 100)
    candidate = ("RobloxPlayerBeta.exe", 321, 456.0, 2, None)
    with pinned_clock(101):
        # No published v3 observation: nothing may be primed or offered.
        early = b.capture_foreground_context()
        assert not b.prime_target_receipt(candidate, early, sample_time=100.25)
        assert not b.publish_target_offer(candidate, early, sample_time=100.25)
    context = observe_v3(b, candidate, 100.25, mono=101)
    b.client.publish.reset_mock()
    with pinned_clock(101):
        assert b.prime_target_receipt(candidate, context, sample_time=100.25)
        assert b.publish_target_offer(candidate, context, sample_time=100.25)
        topics = [c.args[0] for c in b.client.publish.call_args_list]
        assert topics == [b.root + "/state/terminate_offer"]
        assert b._raw_receipt["candidate"] == candidate
        assert not b.publish_target_offer(candidate, context, sample_time=100.25)
        assert not b.prime_target_receipt(candidate, context, sample_time=100.25)


def test_invalid_or_missing_target_receipt_does_not_create_offer():
    import time
    b = Bridge({**CONFIG, "games": []})
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.publish({}, 100)
    b.client.publish.reset_mock()
    valid = ("RobloxPlayerBeta.exe", 321, 456.0, 2, None)
    context = b.capture_foreground_context()
    assert not b.prime_target_receipt(None, context, sample_time=time.monotonic())
    assert not b.publish_target_offer(valid, context, sample_time=time.monotonic())
    assert not b.prime_target_receipt(valid, context, sample_time=0.0)
    assert not b.publish_target_offer(valid, context, sample_time=time.monotonic())
    b.client.publish.assert_not_called()


def test_broker_rejects_legacy_retained_tombstone_without_announcing_online():
    b = connected_bridge()
    ack = b.client.publish.return_value
    rejected = Mock(rc=4)
    b.client.publish.side_effect = (
        lambda topic, *args, **kwargs: rejected
        if topic == b.root + "/state/uptime" else ack)
    assert not b.publish({}, 12)
    assert b.synced_generation is None
    assert b.refresh_requested
    assert not any(c.args[:2] == (b.root + "/availability", "online")
                   for c in b.client.publish.call_args_list)


def test_tombstone_publish_exception_fails_closed_and_retries():
    b = connected_bridge()
    ack = b.client.publish.return_value
    def fail(topic, *args, **kwargs):
        if topic == b.root + "/state/uptime":
            raise OSError("synthetic broker outage")
        return ack
    b.client.publish.side_effect = fail
    assert not b.publish({}, 12)
    assert b.synced_generation is None
    assert b.refresh_requested
    b.client.publish.side_effect = None
    assert b.publish({}, 13)
    assert b.synced_generation == b.generation


def test_target_receipt_requires_same_authenticated_current_context():
    b = Bridge({**CONFIG, "games": []})
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.client.publish.return_value.is_published.return_value = True
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    assert b.publish({}, 12)
    candidate = ("RobloxPlayerBeta.exe", 321, 456.0, 2, None)

    # 1. A superseded context cannot prime, and the observation is single-use.
    first = observe_v3(b, candidate, 100.25, mono=101)
    with pinned_clock(101):
        second = b.capture_foreground_context()
        assert not b.prime_target_receipt(candidate, first, sample_time=100.25)
        assert not b.prime_target_receipt(candidate, second, sample_time=100.25)
    # 2. A non-finite sample time cannot prime.
    context = observe_v3(b, candidate, 200.25, mono=201)
    with pinned_clock(201):
        assert not b.prime_target_receipt(
            candidate, context, sample_time=float("nan"))
    # 3. The same current, authenticated context and exact sample primes.
    context = observe_v3(b, candidate, 300.25, mono=301)
    with pinned_clock(301):
        assert b.prime_target_receipt(candidate, context, sample_time=300.25)
        b.on_disconnect(b.client, None, None, None, None)
        assert not b.publish_target_offer(candidate, context, sample_time=300.25)


def test_clean_cut_tombstones_never_publish_after_disconnect():
    b = connected_bridge()
    generation = b.generation
    b.on_disconnect(b.client, None, None, None, None)
    b.client.publish.reset_mock()
    assert not b._clear_legacy_retained(generation)
    b.client.publish.assert_not_called()


def test_local_rules_cannot_prime_target_offer_without_v3_control_entitlement():
    import time
    b = connected_bridge()  # legacy local rules deliberately disable targeting
    assert b.publish({}, 10)
    context = b.capture_foreground_context()
    candidate = ("RobloxPlayerBeta.exe", 321, 456.0, 2, None)
    assert not b.prime_target_receipt(
        candidate, context, sample_time=time.monotonic())
    assert b._raw_receipt is None


def test_clean_cut_connection_drops_at_last_retained_tombstone_ack():
    b = connected_bridge()
    ack = b.client.publish.return_value
    def transmit(topic, value, **kwargs):
        if topic == b.root + "/state/focus_availability" and value == b"":
            info = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
            info.wait_for_publish.return_value = True
            def finish():
                b.on_disconnect(b.client, None, None, None, None)
                return True
            info.is_published.side_effect = finish
            return info
        return ack
    b.client.publish.side_effect = transmit
    assert not b.publish({}, 12)
    assert b.synced_generation is None
    assert b.refresh_requested
    assert not any(c.args[:2] == (b.root + "/availability", "online")
                   for c in b.client.publish.call_args_list)


def test_read_only_diagnostics_request_survives_invalid_telemetry():
    import json
    b = connected_bridge()
    b.errors.report("WIN_INVALID_SYSTEM_METADATA")
    nonce = b"a" * 32
    request = SimpleNamespace(topic=b.root + "/diagnostics/request", payload=nonce, retain=False)
    b.client.publish.reset_mock()
    b.on_message(b.client, None, request)
    call, = b.client.publish.call_args_list
    assert call.args[0] == b.root + "/diagnostics/response"
    data = json.loads(call.args[1])
    assert data == {"version": 1, "device_id": "pc1", "nonce": nonce.decode(),
                    "active": [{"code": "WIN_INVALID_SYSTEM_METADATA", "occurrences": 1}],
                    "last_resolved": None}
    assert call.kwargs["retain"] is False
    assert list(b.drain_commands()) == []
    b.client.publish.reset_mock()
    request.retain = True
    b.on_message(b.client, None, request)
    assert not b.client.publish.called
