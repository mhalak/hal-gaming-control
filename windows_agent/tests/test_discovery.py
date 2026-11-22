from gaming_control.discovery import discovery, obsolete_discovery_topics


def test_exact_interface():
    a, b = discovery('pc1', 'PC 1'), discovery('pc2', 'PC 2')
    assert len(a) == 3
    assert not set(a).intersection(b)
    root = 'SmartHouse/Gaming/pc1/'
    assert {v['state_topic'] for v in a.values() if 'state_topic' in v} == {
        root + 'state/uptime'}
    assert {v['command_topic'] for v in a.values() if 'command_topic' in v} == {
        root + 'command/terminate_game', root + 'command/lock_pc'}
    for topic, config in a.items():
        assert config['availability_topic'] == root + 'availability'
        assert config['device']['identifiers'] == ['smarthouse_gaming_pc1']
        if '/button/' in topic:
            assert config['retain'] is False and config['qos'] == 0
            assert config['payload_press'] == 'PRESS' and 'state_topic' not in config
    assert not set(a).intersection(obsolete_discovery_topics('pc1', 'homeassistant'))



def test_only_verified_agent_owned_activity_topics_are_retired():
    obsolete = set(obsolete_discovery_topics('pc1', 'homeassistant'))
    for kind, key in (('sensor', 'current_game'), ('sensor', 'active_game'),
                      ('binary_sensor', 'in_game'),
                      ('binary_sensor', 'gaming_active')):
        assert f'homeassistant/{kind}/smarthouse_gaming_pc1_{key}/config' in obsolete
    assert not any('pc2' in topic for topic in obsolete)
    assert set(discovery('pc1', 'PC 1')).isdisjoint(obsolete)
    for keep in ('uptime', 'terminate_game', 'lock_pc'):
        assert any(f'_{keep}/config' in topic
                   for topic in discovery('pc1', 'PC 1'))


def test_no_local_rules_do_not_discover_unsafe_manual_terminate():
    config = discovery("pc1", "PC 1", terminate_enabled=False)
    assert len(config) == 2
    assert not any("_terminate_game/config" in topic for topic in config)
    assert any("_lock_pc/config" in topic for topic in config)
    assert any("_uptime/config" in topic for topic in config)
    assert not set(config).intersection(discovery("pc2", "PC 2"))


def test_explicit_terminate_tombstone_is_device_scoped():
    from gaming_control.discovery import terminate_discovery_topic
    assert terminate_discovery_topic("pc1", "homeassistant") == (
        "homeassistant/button/smarthouse_gaming_pc1_terminate_game/config")



def test_v3_remaps_exact_existing_uptime_discovery_without_new_entity():
    legacy = discovery('pc1', 'PC 1')
    unified = discovery('pc1', 'PC 1', unified_enabled=True)
    assert legacy.keys() == unified.keys()
    assert len(unified) == 3
    topic = 'homeassistant/sensor/smarthouse_gaming_pc1_uptime/config'
    before, after = legacy[topic], unified[topic]
    assert before['unique_id'] == after['unique_id']
    assert before['device'] == after['device']
    assert before['availability_topic'] == after['availability_topic']
    assert before['state_topic'] == 'SmartHouse/Gaming/pc1/state/uptime'
    assert after['state_topic'] == 'SmartHouse/Gaming/pc1/state/telemetry'
    assert 'value_template' not in before and 'expire_after' not in before
    assert 'value_template' in after and after['expire_after'] == 10
    assert "value_json.version == 3" in after['value_template']
    assert "value_json.device_id == 'pc1'" in after['value_template']
    assert "value_json.system.uptime_seconds" in after['value_template']
    assert all(legacy[t] == unified[t] for t in legacy if t != topic)
    assert set(unified).isdisjoint(obsolete_discovery_topics('pc1', 'homeassistant'))


def test_v3_and_v2_native_uptime_reconfiguration_is_reversible():
    from gaming_control.discovery import _uptime_v3_template
    new = discovery('pc2', 'PC 2', 'ha_custom',
                    terminate_enabled=False, unified_enabled=True)
    old = discovery('pc2', 'PC 2', 'ha_custom',
                    terminate_enabled=False, unified_enabled=False)
    topic = 'ha_custom/sensor/smarthouse_gaming_pc2_uptime/config'
    assert set(new) == set(old) and len(new) == 2
    assert new[topic]['state_topic'].endswith('/pc2/state/telemetry')
    assert old[topic]['state_topic'].endswith('/pc2/state/uptime')
    assert new[topic]['unique_id'] == old[topic]['unique_id']
    assert 'expire_after' not in old[topic]
    assert 'pc1' not in _uptime_v3_template('pc2')
    assert set(new).isdisjoint(obsolete_discovery_topics('pc2', 'ha_custom'))


def test_untrusted_device_id_never_reaches_native_template():
    import pytest
    for bad in ("", "pc/1", "pc' or true", "a" * 65, "../../pc2", None):
        with pytest.raises(ValueError):
            discovery(bad, 'PC', unified_enabled=True)
