def discovery(device_id, name, prefix='homeassistant', *, terminate_enabled=True):
    root = f'SmartHouse/Gaming/{device_id}'
    device = {'identifiers': [f'smarthouse_gaming_{device_id}'], 'name': name,
              'manufacturer': 'SmartHouse', 'model': 'Windows Gaming Agent'}
    specs = {
        'uptime': ('sensor', 'Uptime', {'unit_of_measurement': 's', 'device_class': 'duration', 'entity_category': 'diagnostic'}),
        'terminate_game': ('button', 'Terminate game', {}),
        'lock_pc': ('button', 'Lock PC', {}),
    }
    if not terminate_enabled:
        del specs['terminate_game']
    result = {}
    for key, (component, label, extra) in specs.items():
        uid = f'smarthouse_gaming_{device_id}_{key}'
        data = {'name': label, 'unique_id': uid, 'device': device,
                'availability_topic': root + '/availability', **extra}
        if component == 'button':
            data.update(command_topic=root + '/command/' + key, qos=0,
                        retain=False, payload_press='PRESS')
        else:
            # #176 clean cut: preserve the same entity and unique_id while
            # reading Uptime solely from the versioned, non-retained v3 packet.
            # expire_after is needed because availability can remain 'online'
            # if the live telemetry helper stalls.
            data['state_topic'] = root + '/state/telemetry'
            data['expire_after'] = 10
            data['value_template'] = (
                "{{ value_json.system.uptime_seconds "
                "if value_json is mapping and value_json.version == 3 "
                "and value_json.device_id == '" + device_id + "' "
                "and value_json.system is mapping "
                "and value_json.system.uptime_seconds is number "
                "and value_json.system.uptime_seconds is not boolean "
                "and 0 <= value_json.system.uptime_seconds <= 9223372036854775807 "
                "else 'unavailable' }}"
            )
        result[f'{prefix}/{component}/{uid}/config'] = data
    return result


def obsolete_discovery_topics(device_id, prefix):
    # One-time compatibility cleanup for an earlier development preview.
    old = {'sensor': ('remaining', 'played', 'game', 'current_game', 'active_game'),
           'binary_sensor': ('active', 'allowed', 'in_game', 'gaming_active'),
           'switch': ('enabled', 'unlimited'),
           'number': ('minutes',),
           'button': ('add15', 'add30', 'add60', 'reset')}
    return [f'{prefix}/{component}/smarthouse_gaming_{device_id}_{key}/config'
            for component, keys in old.items() for key in keys]


def terminate_discovery_topic(device_id, prefix):
    """Exact native MQTT discovery topic owned by this agent's old button."""
    return f'{prefix}/button/smarthouse_gaming_{device_id}_terminate_game/config'
