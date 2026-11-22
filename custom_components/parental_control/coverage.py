"""Bound historical accounting by observed uptime heartbeats."""
from bisect import bisect_right
from .liveness import MAX_HEARTBEAT_AGE

MAX_CLOCK_SKEW = 15


def heartbeat_intervals(samples):
    """Return intervals bounded by consistent, consecutive observed uptimes.
    Missing/unknown samples, reboots and long gaps break coverage.
    """
    intervals = []
    previous = None
    for ts, raw in sorted(dict(samples).items()):
        try:
            value = int(raw)
            if value < 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            previous = None
            continue
        if previous:
            before, old = previous
            elapsed, progress = ts - before, value - old
            if (0 < elapsed <= MAX_HEARTBEAT_AGE and progress > 0
                    and abs(progress - elapsed) <= MAX_CLOCK_SKEW):
                if intervals and intervals[-1][1] == before:
                    intervals[-1] = (intervals[-1][0], ts)
                else:
                    intervals.append((before, ts))
        previous = (ts, value)
    return intervals


def covered_transitions(transitions, intervals):
    """Mask unobserved intervals as unavailable while retaining game transitions."""
    ordered = sorted(dict(transitions).items())
    times = [ts for ts, _ in ordered]
    output = {}
    for start, end in intervals:
        if start >= end:
            continue
        i = bisect_right(times, start)
        output[start] = ordered[i - 1][1] if i else "unavailable"
        while i < len(ordered) and ordered[i][0] < end:
            ts, value = ordered[i]
            output[ts] = value
            i += 1
        output[end] = "unavailable"
    return sorted(output.items())


def _foreground_value(game, active, enrolled):
    if active == "off" and game == "idle":
        return "idle"
    if (active == "on" and isinstance(game, str)
            and game not in ("", "idle", "unknown", "unavailable")
            and " | " not in game and game in enrolled):
        return game
    return "unavailable"


def confirmed_foreground_transitions(game_states, active_states, enrolled, boundary):
    """Normalize paired HA state histories after a supplied cutover timestamp.

    This only validates reported state consistency; heartbeat coverage, live
    freshness and a durable cutover must be established by the caller.
    Never carry a pre-cutover observation into the new accounting epoch.
    """
    games = {ts: value for ts, value in game_states if ts >= boundary}
    flags = {ts: value for ts, value in active_states if ts >= boundary}
    enrolled = set(enrolled)
    game = flag = None
    output = []
    for ts in sorted(games.keys() | flags.keys() | {boundary}):
        if ts in games:
            game = games[ts]
        if ts in flags:
            flag = flags[ts]
        value = _foreground_value(game, flag, enrolled)
        if not output or output[-1][1] != value:
            output.append((ts, value))
    return output
