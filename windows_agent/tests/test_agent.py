from unittest.mock import Mock, patch
import psutil
from gaming_control.agent import execute, stop_games

RULES = [{'name': 'Roblox', 'process': 'RobloxPlayerBeta.exe'}]


def test_explicit_dispatch():
    with patch('gaming_control.agent.stop_games') as terminate, patch('gaming_control.agent.lock_active_session') as lock:
        execute('terminate_game', RULES)
        terminate.assert_called_once_with(RULES)
        lock.assert_not_called()
        execute('lock_pc', RULES)
        lock.assert_called_once_with()


def test_pid_reuse_not_terminated():
    old = Mock(pid=123)
    new = Mock()
    new.create_time.return_value = 20
    with patch('gaming_control.agent.scan', return_value=[(old, 'Roblox', 10)]), patch('gaming_control.agent.psutil.Process', return_value=new):
        stop_games(RULES)
    new.terminate.assert_not_called()


def test_changed_identity_not_terminated():
    old = Mock(pid=123)
    old.is_running.return_value = True
    new = Mock()
    new.create_time.return_value = 10
    new.name.return_value = 'notepad.exe'
    with patch('gaming_control.agent.scan', return_value=[(old, 'Roblox', 10)]), patch('gaming_control.agent.psutil.Process', return_value=new):
        stop_games(RULES)
    new.terminate.assert_not_called()


def test_matched_identity_terminated():
    old = Mock(pid=123)
    old.is_running.return_value = True
    new = Mock(pid=123)
    new.create_time.return_value = 10
    new.name.return_value = 'RobloxPlayerBeta.exe'
    new.is_running.return_value = True
    with patch('gaming_control.agent.scan', return_value=[(old, 'Roblox', 10)]), patch('gaming_control.agent.psutil.Process', return_value=new):
        stop_games(RULES)
    new.terminate.assert_called_once_with()


def test_first_scan_and_process_identity_changes_logged(caplog):
    import logging
    from gaming_control.agent import log_game_changes
    proc = Mock(pid=321)
    proc.exe.return_value = r'C:\Roblox\RobloxPlayerBeta.exe'
    with caplog.at_level(logging.INFO), patch('gaming_control.agent.process_session_id', return_value=2):
        previous = log_game_changes([], None)
        previous = log_game_changes([(proc,'Roblox',10)], previous)
        previous = log_game_changes([(proc,'Roblox',10)], previous)
        previous = log_game_changes([(proc,'Roblox',20)], previous)
        log_game_changes([], previous)
    assert 'Initial live game scan' in caplog.text
    assert caplog.text.count('Game detected: Roblox') == 2
    assert caplog.text.count('Game no longer detected: Roblox') == 2
    assert 'pid=321' in caplog.text
    assert 'session=2' in caplog.text
