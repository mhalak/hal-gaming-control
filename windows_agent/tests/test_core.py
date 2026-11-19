import pytest
from gaming_control.core import game_state, match_game, validate_rules
from gaming_control.windows import select_session

RULES = [
    {'name': 'Minecraft Java', 'process': 'javaw.exe', 'command_line_arg': 'net.minecraft.client.main.Main'},
    {'name': 'Roblox', 'process': 'RobloxPlayerBeta.exe'},
]


def test_java_matching():
    assert match_game({'name': 'JAVAW.EXE', 'cmdline': ['javaw.exe', 'net.minecraft.client.main.Main']}, RULES) == 'Minecraft Java'
    assert match_game({'name': 'javaw.exe', 'cmdline': ['javaw.exe', 'other.Main']}, RULES) is None
    assert match_game({'name': 'javaw.exe', 'cmdline': None}, RULES) is None


def test_game_state():
    assert game_state([]) == {'in_game': 'OFF', 'current_game': 'idle'}
    assert game_state(['Roblox', 'Minecraft Java', 'Roblox']) == {
        'in_game': 'ON', 'current_game': 'Minecraft Java | Roblox'}


@pytest.mark.parametrize('rules', [[], [{'name': 'All Java', 'process': 'javaw.exe'}],
    [{'name': 'idle', 'process': 'game.exe'}], [{'name': 'bad | delimiter', 'process': 'game.exe'}],
    [{'name': 'Bad', 'process': 'game.exe', 'path_contains': ''}]])
def test_invalid_rules(rules):
    with pytest.raises(ValueError):
        validate_rules(rules)


def test_valid_rules():
    assert validate_rules(RULES) == RULES


def test_session_selection():
    active = 0
    sessions = [{'SessionId': 0, 'State': active}, {'SessionId': 1, 'State': active},
                {'SessionId': 2, 'State': active}, {'SessionId': 3, 'State': 4}]
    assert select_session(sessions, 2, active) == 2
    assert select_session(sessions, 99, active) is None
    assert select_session(sessions[:2], 99, active) == 1
    assert select_session([], 99, active) is None
