from gaming_control.discovery import discovery, obsolete_discovery_topics


def test_exact_interface():
    a, b = discovery('pc1', 'PC 1'), discovery('pc2', 'PC 2')
    assert len(a) == 7
    assert not set(a).intersection(b)
    root = 'SmartHouse/Gaming/pc1/'
    assert {v['state_topic'] for v in a.values() if 'state_topic' in v} == {
        root + 'state/uptime', root + 'state/in_game', root + 'state/current_game',
        root + 'state/gaming_active', root + 'state/active_game'}
    assert {v['command_topic'] for v in a.values() if 'command_topic' in v} == {
        root + 'command/terminate_game', root + 'command/lock_pc'}
    for topic, config in a.items():
        if topic.endswith(('_gaming_active/config', '_active_game/config')):
            assert config['availability_mode'] == 'all'
            assert config['availability'] == [{'topic': root+'availability'}, {'topic': root+'state/focus_availability'}]
        else:
            assert config['availability_topic'] == root + 'availability'
        assert config['device']['identifiers'] == ['smarthouse_gaming_pc1']
        if '/button/' in topic:
            assert config['retain'] is False and config['qos'] == 0
            assert config['payload_press'] == 'PRESS' and 'state_topic' not in config
    assert not set(a).intersection(obsolete_discovery_topics('pc1', 'homeassistant'))
