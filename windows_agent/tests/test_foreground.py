from unittest.mock import Mock
import pytest
import psutil
from gaming_control.foreground import classify, IDLE, UNKNOWN

RULES = [{"name":"Roblox","process":"RobloxPlayerBeta.exe"},
         {"name":"Minecraft Java","process":"javaw.exe","command_line_arg":"net.minecraft.client.main.Main"}]


@pytest.mark.parametrize("name,args,expected", [
    ("RobloxPlayerBeta.exe", [], "Roblox"),
    ("javaw.exe", ["net.minecraft.client.main.Main"], "Minecraft Java"),
    ("javaw.exe", ["launcher"], "idle"),
    ("chrome.exe", [], "idle"),
])
def test_single_foreground_game(name,args,expected):
    proc = Mock()
    proc.name.return_value = name
    proc.cmdline.return_value = args
    proc.create_time.return_value = 123
    proc.is_running.return_value = True
    result = classify({"time":10,"status":"window","pid":42,"created":123},2,10.5,RULES,
                      process_factory=lambda pid:proc, session_lookup=lambda pid:2)
    assert result == {"gaming_active":"OFF" if expected=="idle" else "ON","active_game":expected}


def test_idle_unknown_stale_and_wrong_identity():
    assert classify({"time":10,"status":"idle"},2,10.5,RULES) == IDLE
    assert classify({"time":10,"status":"idle"},2,12,RULES) == UNKNOWN
    assert classify(None,2,10,RULES) == UNKNOWN
    proc = Mock()
    proc.create_time.return_value = 124
    assert classify({"time":10,"status":"window","pid":42,"created":123},2,10.5,RULES,
                    process_factory=lambda pid:proc, session_lookup=lambda pid:2) == UNKNOWN
    proc.create_time.return_value = 123
    assert classify({"time":10,"status":"window","pid":42,"created":123},2,10.5,RULES,
                    process_factory=lambda pid:proc, session_lookup=lambda pid:3) == UNKNOWN


VALID_SAMPLE = {"time": 10, "status": "window", "pid": 42, "created": 123}


def running_process():
    proc = Mock()
    proc.create_time.return_value = 123
    proc.is_running.return_value = True
    proc.name.return_value = "RobloxPlayerBeta.exe"
    return proc


@pytest.mark.parametrize("sample,session,now", [
    (VALID_SAMPLE, True, 10),
    (VALID_SAMPLE, 0, 10),
    (VALID_SAMPLE, 2, 9.99),
    (VALID_SAMPLE, 2, 11.5001),
    (VALID_SAMPLE | {"time": float("nan")}, 2, 10),
    (VALID_SAMPLE | {"time": True}, 2, 10),
    (VALID_SAMPLE | {"status": "unknown"}, 2, 10),
    (VALID_SAMPLE | {"pid": True}, 2, 10),
    (VALID_SAMPLE | {"pid": 0}, 2, 10),
    (VALID_SAMPLE | {"created": float("inf")}, 2, 10),
])
def test_invalid_sample_never_opens_process(sample, session, now):
    factory = Mock()
    assert classify(sample, session, now, RULES, factory, Mock()) == UNKNOWN
    factory.assert_not_called()


@pytest.mark.parametrize("age", [0, 1.5])
def test_sample_age_boundaries_and_minimal_metadata(age):
    proc = running_process()
    assert classify(VALID_SAMPLE, 2, 10 + age, RULES, lambda pid: proc, lambda pid: 2) == {
        "gaming_active": "ON", "active_game": "Roblox"}
    proc.exe.assert_not_called()
    proc.cmdline.assert_not_called()


@pytest.mark.parametrize("running,created", [([True, False], [123]),
                                               ([True, True], [123, 124])])
def test_process_identity_rechecked_after_matching(running, created):
    proc = running_process()
    proc.is_running.side_effect = running
    proc.create_time.side_effect = created
    assert classify(VALID_SAMPLE, 2, 10, RULES, lambda pid: proc, lambda pid: 2) == UNKNOWN
    proc.name.assert_called_once()


def test_path_constraint_and_case_insensitive_name():
    proc = running_process()
    proc.name.return_value = "GAME.EXE"
    proc.exe.return_value = r"C:\Games\Example\game.exe"
    rules = [{"name": "Example", "process": "game.exe", "path_contains": "games/example"}]
    assert classify(VALID_SAMPLE, 2, 10, rules, lambda pid: proc, lambda pid: 2) == {
        "gaming_active": "ON", "active_game": "Example"}
    proc.cmdline.assert_not_called()
    proc.exe.return_value = r"C:\Other\game.exe"
    assert classify(VALID_SAMPLE, 2, 10, rules, lambda pid: proc, lambda pid: 2) == IDLE


@pytest.mark.parametrize("error", [psutil.AccessDenied(), psutil.NoSuchProcess(42),
                                   OSError("synthetic"), ValueError("synthetic")])
def test_process_lookup_failure_is_unknown(error):
    factory = Mock(side_effect=error)
    assert classify(VALID_SAMPLE, 2, 10, RULES, factory, lambda pid: 2) == UNKNOWN


def test_missing_session_lookup_is_unknown():
    proc = running_process()
    assert classify(VALID_SAMPLE, 2, 10, RULES, lambda pid: proc) == UNKNOWN
    proc.name.assert_not_called()
