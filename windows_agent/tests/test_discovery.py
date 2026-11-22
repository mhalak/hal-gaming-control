from gaming_control.discovery import discovery, obsolete_discovery_topics


def test_exact_interface():
    a, b = discovery('pc1', 'PC 1'), discovery('pc2', 'PC 2')
    assert len(a) == 3
    assert not set(a).intersection(b)
    root = 'SmartHouse/Gaming/pc1/'
    assert {v['state_topic'] for v in a.values() if 'state_topic' in v} == {
        root + 'state/telemetry'}
    uptime = a['homeassistant/sensor/smarthouse_gaming_pc1_uptime/config']
    assert uptime['unique_id'] == 'smarthouse_gaming_pc1_uptime'
    assert uptime['expire_after'] == 10
    assert 'value_json.system.uptime_seconds' in uptime['value_template']
    assert "value_json.device_id == 'pc1'" in uptime['value_template']
    assert 'unavailable' in uptime['value_template']
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
