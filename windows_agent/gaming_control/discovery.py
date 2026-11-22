def _uptime_v3_template(device_id):
    """A single native MQTT sensor reads only bounded same-device v3 uptime."""
    # Trust only locally provisioned device IDs; avoid template injection.
    import re
    if not isinstance(device_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", device_id):
        raise ValueError("Invalid Uptime discovery device ID")
    return (
        "{{ value_json.system.uptime_seconds if "
        "value_json.version == 3 and "
        f"value_json.device_id == '{device_id}' and "
        "value_json.system is defined and "
        "value_json.system.uptime_seconds is defined and "
        "value_json.system.uptime_seconds is number and "
        "value_json.system.uptime_seconds is not boolean and "
        "0 <= value_json.system.uptime_seconds <= 9223372036854775807 "
        "else 'unknown' }}"
    )


def discovery(device_id, name, prefix='homeassistant', *,
              terminate_enabled=True, unified_enabled=False):
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
            if key == 'uptime' and unified_enabled:
                data['state_topic'] = root + '/state/telemetry'
                data['value_template'] = _uptime_v3_template(device_id)
                data['expire_after'] = 10
            else:
                data['state_topic'] = root + '/state/' + key
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
