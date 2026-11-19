from unittest.mock import Mock
import pytest
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
