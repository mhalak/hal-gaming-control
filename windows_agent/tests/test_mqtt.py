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


def test_state_changes_and_uptime_period():
    b = connected_bridge()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=10):
        b.publish({'in_game': 'OFF', 'current_game': 'idle'}, 100)
    topics = {call.args[0] for call in b.client.publish.call_args_list}
    assert b.root + '/state/uptime' in topics
    assert b.root + '/availability' in topics
    b.client.publish.reset_mock()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=11):
        b.publish({'in_game': 'ON', 'current_game': 'Roblox'}, 101)
    assert {call.args[0] for call in b.client.publish.call_args_list} == {
        b.root + '/state/in_game', b.root + '/state/current_game'}
    b.client.publish.reset_mock()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=70):
        b.publish({'in_game': 'ON', 'current_game': 'Roblox'}, 160)
    assert b.root + '/state/uptime' in {call.args[0] for call in b.client.publish.call_args_list}


def test_republish_on_reconnect():
    b = connected_bridge()
    values = {'in_game': 'OFF', 'current_game': 'idle'}
    b.publish(values, 100)
    b.on_disconnect(b.client, None, None, None, None)
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    b.client.publish.reset_mock()
    b.publish(values, 101)
    topics = {call.args[0] for call in b.client.publish.call_args_list}
    assert {b.root + '/state/' + k for k in ('uptime', 'in_game', 'current_game')} <= topics


def test_versioned_custom_discovery():
    import json
    b = connected_bridge()
    b.publish({'in_game': 'OFF', 'current_game': 'idle'}, 100)
    calls = [c for c in b.client.publish.call_args_list if c.args[0] == b.root + '/discovery']
    assert len(calls) == 1 and calls[0].kwargs['retain']
    data = json.loads(calls[0].args[1])
    assert data['protocol_version'] == 1 and data['device_id'] == 'pc1'
    assert data['actions'] == ['terminate_game', 'lock_pc']


def test_startup_offline_until_all_live_values_are_confirmed():
    b = connected_bridge()
    assert b.publish({'in_game':'OFF','current_game':'idle'}, 12)
    calls = [(c.args[0], c.args[1], c.kwargs) for c in b.client.publish.call_args_list
             if c.args[0].startswith(b.root + '/state/') or c.args[0] == b.root + '/availability']
    assert calls == [
        (b.root+'/availability','offline',{'qos':1,'retain':True}),
        (b.root+'/state/in_game','OFF',{'qos':1,'retain':True}),
        (b.root+'/state/current_game','idle',{'qos':1,'retain':True}),
        (b.root+'/state/uptime','12',{'qos':1,'retain':True}),
        (b.root+'/availability','online',{'qos':1,'retain':True}),
    ]


def test_initial_snapshot_timeout_never_announces_online():
    b = connected_bridge()
    ack = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    ack.is_published.return_value = True
    lost = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    lost.is_published.return_value = False
    def deliver(topic, *args, **kwargs):
        return lost if topic.endswith('/state/current_game') else ack
    b.client.publish.side_effect = deliver
    assert not b.publish({'in_game':'OFF','current_game':'idle'}, 12)
    assert b.synced_generation is None
    assert b.refresh_requested
    assert not any(c.args[:2] == (b.root+'/availability','online')
                   for c in b.client.publish.call_args_list)
    b.client.publish.side_effect = None
    assert b.publish({'in_game':'OFF','current_game':'idle'}, 13)


def test_disconnect_during_snapshot_requires_fresh_scan():
    b = connected_bridge()
    ack = b.client.publish.return_value
    def disconnect():
        b.on_disconnect(b.client, None, None, None, None)
    def deliver(topic, *args, **kwargs):
        if topic.endswith('/state/current_game'):
            disconnect()
        return ack
    b.client.publish.side_effect = deliver
    assert not b.publish({'in_game':'ON','current_game':'Roblox'}, 12)
    assert b.synced_generation is None
    b.on_connect(b.client,None,None,SimpleNamespace(is_failure=False),None)
    b.client.publish.side_effect = None
    b.client.publish.reset_mock()
    assert b.publish({'in_game':'OFF','current_game':'idle'},13)
    assert any(c.args[:2] == (b.root+'/state/current_game','idle')
               for c in b.client.publish.call_args_list)
    assert not any(c.args[:2] == (b.root+'/state/current_game','Roblox')
                   for c in b.client.publish.call_args_list)


def test_failed_game_transition_invalidates_and_retries_complete_snapshot():
    b = connected_bridge()
    assert b.publish({'in_game':'ON','current_game':'Roblox'}, 12)
    ack = b.client.publish.return_value
    lost = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    lost.is_published.return_value = False
    b.client.publish.side_effect = lambda topic,*a,**k: lost if topic.endswith('/state/current_game') else ack
    assert not b.publish({'in_game':'OFF','current_game':'idle'},13)
    assert b.synced_generation is None
    assert b.client.publish.call_args.args[:2] == (b.root+'/availability','offline')
    b.client.publish.side_effect = None
    assert b.publish({'in_game':'OFF','current_game':'idle'},14)
    assert b.last['current_game'] == 'idle'
    assert b.last['in_game'] == 'OFF'


def test_disconnected_publish_never_sends_telemetry():
    b = connected_bridge()
    b.on_disconnect(b.client, None, None, None, None)
    b.client.publish.reset_mock()
    assert not b.publish({'gaming_active': 'ON', 'active_game': 'Roblox'}, 12)
    b.client.publish.assert_not_called()
    assert b.synced_generation is None
    assert b.refresh_requested


def test_unknown_focus_hides_previous_state_before_publishing_pair():
    b = connected_bridge()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=10):
        assert b.publish({'gaming_active': 'ON', 'active_game': 'Roblox'}, 12)
    b.client.publish.reset_mock()
    values = {'gaming_active': 'UNKNOWN', 'active_game': 'unknown'}
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=11):
        assert b.publish(values, 13)
    assert [(c.args[0], c.args[1]) for c in b.client.publish.call_args_list] == [
        (b.root + '/state/focus_availability', 'offline'),
        (b.root + '/state/gaming_active', 'UNKNOWN'),
        (b.root + '/state/active_game', 'unknown'),
    ]
    assert values == {'gaming_active': 'UNKNOWN', 'active_game': 'unknown'}


def test_unchanged_sample_does_not_republish_before_uptime_deadline():
    b = connected_bridge()
    values = {'gaming_active': 'OFF', 'active_game': 'idle'}
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=10):
        assert b.publish(values, 12)
    b.client.publish.reset_mock()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=69.99):
        assert b.publish(values, 71)
    b.client.publish.assert_not_called()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=70):
        assert b.publish(values, 72)
    assert any(c.args[:2] == (b.root + '/state/uptime', '72')
               for c in b.client.publish.call_args_list)


def test_home_assistant_restart_forces_discovery_and_full_snapshot():
    b = connected_bridge()
    values = {'gaming_active': 'OFF', 'active_game': 'idle'}
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=10):
        assert b.publish(values, 12)
    b.on_message(b.client, None, SimpleNamespace(topic=b.prefix + '/status', payload=b'online'))
    b.client.publish.reset_mock()
    with patch('gaming_control.mqtt_bridge.time.monotonic', return_value=11):
        assert b.publish(values, 13)
    calls = b.client.publish.call_args_list
    assert any(c.args[0] == b.root + '/discovery' for c in calls)
    assert any(c.args[:2] == (b.root + '/state/uptime', '13') for c in calls)
    assert calls[-1].args[:2] == (b.root + '/availability', 'online')
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
    assert b.last['active_game'] == 'idle'


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
    assert set(b.command_topics.values()) == {"lock_pc"}
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
