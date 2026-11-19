from datetime import datetime, timezone
from custom_components.smarthouse_gaming.coverage import heartbeat_intervals, covered_transitions
from custom_components.smarthouse_gaming.rule_engine import usage


def seconds(games, uptime, end, game=None):
    return usage(covered_transitions(games, heartbeat_intervals(uptime)),
                 datetime.fromtimestamp(0, timezone.utc),
                 datetime.fromtimestamp(end, timezone.utc), game)


def test_long_silent_gap_is_not_gameplay():
    games = [(0,"Roblox"), (3660,"idle")]
    uptime = [(0,"100"),(60,"160"),(3600,"3700"),(3660,"3760")]
    assert heartbeat_intervals(uptime) == [(0,60),(3600,3660)]
    assert seconds(games,uptime,3700) == 120


def test_unknown_restart_and_reboot():
    uptime = [(0,"100"),(60,"160"),(65,"unavailable"),(100,"200"),(160,"260"),
              (220,"1"),(280,"61")]
    assert heartbeat_intervals(uptime) == [(0,60),(100,160),(220,280)]
    assert seconds([(0,"Roblox")],uptime,1000) == 180


def test_game_changes_inside_coverage():
    games = [(0,"idle"),(10,"Minecraft | Roblox"),(35,"Roblox"),(50,"unavailable"),(80,"Roblox")]
    uptime = [(0,"100"),(60,"160"),(120,"220")]
    assert seconds(games,uptime,150) == 80
    assert seconds(games,uptime,150,"Minecraft") == 25
    assert seconds(games,uptime,150,"Roblox") == 80


def test_stale_and_clock_jumps():
    assert heartbeat_intervals([(0,"100"),(60,"100"),(120,"500"),(180,"560")]) == [(120,180)]
    assert seconds([(0,"Roblox")],[(0,"100")],1000) == 0
