from datetime import datetime, timezone
from custom_components.hal_gaming_control.coverage import heartbeat_intervals, covered_transitions
from custom_components.hal_gaming_control.rule_engine import usage


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


# The foreground source is a pair of Recorder streams, not the legacy
# process-presence list. This pure normalization is not yet wired into HA.
def foreground(games, flags, boundary=0, enrolled=("Roblox", "Minecraft")):
    from custom_components.hal_gaming_control.coverage import confirmed_foreground_transitions
    return confirmed_foreground_transitions(games, flags, enrolled, boundary)


def test_foreground_pair_only_counts_confirmed_single_application():
    games = [(0, "Roblox"), (20, "idle"), (40, "Minecraft"), (80, "idle")]
    flags = [(0, "on"), (20, "off"), (40, "on"), (80, "off")]
    assert foreground(games, flags) == [(0, "Roblox"), (20, "idle"),
                                        (40, "Minecraft"), (80, "idle")]


def test_foreground_asynchronous_pair_inconsistency_is_unavailable():
    games = [(0, "idle"), (15, "Roblox"), (45, "idle")]
    flags = [(0, "off"), (10, "on"), (50, "off")]
    assert foreground(games, flags) == [(0, "idle"), (10, "unavailable"),
                                        (15, "Roblox"), (45, "unavailable"), (50, "idle")]


def test_foreground_missing_or_unknown_is_not_confirmed_idle():
    games = [(0, "idle"), (20, "unknown"), (40, "idle"), (60, "Roblox")]
    flags = [(10, "off"), (30, "unavailable"), (50, "off"), (70, "on")]
    assert foreground(games, flags) == [(0, "unavailable"), (10, "idle"),
                                        (20, "unavailable"), (50, "idle"),
                                        (60, "unavailable"), (70, "Roblox")]


def test_foreground_migration_boundary_never_uses_earlier_observations():
    games = [(0, "Roblox"), (70, "Minecraft"), (100, "idle")]
    flags = [(0, "on"), (80, "on"), (100, "off")]
    assert foreground(games, flags, boundary=60) == [
        (60, "unavailable"), (80, "Minecraft"), (100, "idle")]


def test_foreground_boundary_includes_new_observation_exactly_at_cutover():
    assert foreground([(0, "Roblox"), (60, "idle")],
                      [(0, "on"), (60, "off")], boundary=60) == [(60, "idle")]


def test_foreground_never_treats_process_lists_or_unenrolled_apps_as_valid():
    games = [(0, "Roblox | Minecraft"), (10, "Browser"), (20, "Roblox")]
    assert foreground(games, [(0, "on")]) == [(0, "unavailable"), (20, "Roblox")]


def test_foreground_same_timestamp_changes_are_grouped_and_last_value_wins():
    games = [(30, "Minecraft"), (0, "idle"), (30, "Roblox")]
    flags = [(30, "off"), (0, "off"), (30, "on")]
    assert foreground(games, flags) == [(0, "idle"), (30, "Roblox")]


def test_foreground_empty_input_is_unavailable_from_boundary():
    assert foreground([], [], boundary=50) == [(50, "unavailable")]
    assert foreground([(60, "Roblox")], [], boundary=50) == [(50, "unavailable")]


def test_foreground_composes_with_heartbeat_coverage_and_per_app_usage():
    games = [(0, "Roblox"), (20, "idle"), (40, "Minecraft"), (80, "unknown"),
             (100, "Minecraft"), (180, "idle")]
    flags = [(0, "on"), (20, "off"), (40, "on"), (80, "unavailable"),
             (100, "on"), (180, "off")]
    normalized = foreground(games, flags)
    uptime = [(0, "100"), (60, "160"), (120, "220"), (180, "280")]
    assert seconds(normalized, uptime, 200) == 140
    assert seconds(normalized, uptime, 200, "Roblox") == 20
    assert seconds(normalized, uptime, 200, "Minecraft") == 120


def test_foreground_heartbeat_gap_remains_unobserved():
    normalized = foreground([(0, "Roblox"), (180, "idle"), (200, "Minecraft")],
                            [(0, "on"), (180, "off"), (200, "on")])
    uptime = [(0, "100"), (60, "160"), (180, "280"), (240, "340")]
    assert seconds(normalized, uptime, 300) == 100


def test_reserved_foreground_names_cannot_be_confirmed_even_if_enrolled():
    names = ["", "idle", "unknown", "unavailable", "Roblox | Minecraft"]
    assert foreground(list(enumerate(names)), [(0, "on")], enrolled=names) == [
        (0, "unavailable")]
    assert foreground([(0, None), (1, "Roblox")], [(0, "on")]) == [
        (0, "unavailable"), (1, "Roblox")]
