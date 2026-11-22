"""Game identification and sensor formatting; no policy or persistence."""

IDLE = 'idle'
SEPARATOR = ' | '
COMMANDS = ('terminate_game', 'lock_pc')


def validate_rules(rules):
    if not isinstance(rules, list):
        raise ValueError('games must be a list')
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - {'name', 'process', 'command_line_arg', 'path_contains'}:
            raise ValueError('Invalid game rule keys')
        for key in ('name', 'process'):
            if not isinstance(rule.get(key), str) or not rule[key].strip():
                raise ValueError(f'Missing {key} in game rule')
        if rule['name'] == IDLE or SEPARATOR in rule['name'] or len(rule['name']) > 80:
            raise ValueError('Reserved or invalid game name')
        for key in ('path_contains', 'command_line_arg'):
            if key in rule and (not isinstance(rule[key], str) or not rule[key].strip()):
                raise ValueError(f'Invalid {key}')
        if rule['process'].casefold() in ('java.exe', 'javaw.exe', 'python.exe', 'pythonw.exe') and not (
            rule.get('command_line_arg') or rule.get('path_contains')
        ):
            raise ValueError('Generic runtime requires an additional identity constraint')
    return rules


def match_game(info, rules):
    name = (info.get('name') or '').casefold()
    exe = (info.get('exe') or '').replace('\\', '/').casefold()
    args = [str(x).casefold() for x in (info.get('cmdline') or [])]
    for rule in rules:
        if name != rule['process'].casefold():
            continue
        if 'command_line_arg' in rule and rule['command_line_arg'].casefold() not in args:
            continue
        if 'path_contains' in rule and rule['path_contains'].replace('\\', '/').casefold() not in exe:
            continue
        return rule['name']
    return None


def game_state(names):
    names = sorted(set(names))
    return {'in_game': 'ON' if names else 'OFF',
            'current_game': SEPARATOR.join(names) if names else IDLE}
