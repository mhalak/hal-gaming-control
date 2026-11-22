"""Pure rule evaluation and calendar windows. All timestamps are timezone-aware."""
from datetime import datetime, timedelta, time
from .const import DEFAULTS
from .protocol import games_from_state


def windows(now):
    day = now.date()
    monday = day - timedelta(days=day.weekday())
    def midnight(d):
        return datetime.combine(d, time.min, tzinfo=now.tzinfo)
    return {"daily": midnight(day), "weekly": midnight(monday),
            "weekend_total": midnight(monday + timedelta(days=5))}


def usage(transitions, start, end, game=None):
    """Integrate transitions (epoch seconds, state). Unknown/unavailable are not play.
    Do not count overlapping games more than once for overall usage.
    """
    a, b = start.timestamp(), end.timestamp()
    if a >= b:
        return 0
    cursor, state, total = a, None, 0.0
    def playing(value):
        active = games_from_state(value)
        return game in active if game is not None else bool(active)
    for ts, value in sorted(transitions, key=lambda x: x[0]):
        if ts <= a:
            state = value
            continue
        if ts >= b:
            break
        if playing(state):
            total += ts - cursor
        state, cursor = value, ts
    if playing(state):
        total += b - cursor
    return max(0, total)


def calculate(transitions, now, games):
    spans = windows(now)
    result = {key: usage(transitions, start, now) for key, start in spans.items()}
    result["per_game"] = {g: usage(transitions, spans["daily"], now, g) for g in games}
    return result


def _validated_weekend_bonus(value):
    """Validate the additive weekend bonus; missing entries use zero."""
    if type(value) is not int or not 0 <= value <= 600 or value % 10:
        raise ValueError("Invalid weekend bonus: expected 0–600 minutes in steps of 10")
    return value


def effective_daily(options, weekend):
    """Only additive weekend bonuses exist in the active policy."""
    bonus = _validated_weekend_bonus(options.get("weekend_bonus", 0))
    base = options["daily"]
    return base + bonus if weekend and base >= 0 else base


def daily_bonus_minutes(options, now):
    """Only today's bonus is active (local calendar date, not rolling 24h)."""
    if options.get("bonus_date") != now.date().isoformat():
        return 0
    value = options.get("bonus_minutes", 0)
    return value if type(value) is int and value >= 0 else 0


def effective_budget_limit(options, now, period):
    options = DEFAULTS | options
    if period == "weekly":
        return options["weekly"]
    if period != "daily":
        raise ValueError("Unsupported budget period")
    base = effective_daily(options, now.weekday() >= 5)
    return base + daily_bonus_minutes(options, now) if base >= 0 else base


def inside_schedule(now, start, end):
    start, end = time.fromisoformat(start), time.fromisoformat(end)
    current = now.time().replace(tzinfo=None)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _schedule_for_weekday(options, weekday):
    """Return the window anchored to this local day; weekends may inherit."""
    start, end = options["schedule_start"], options["schedule_end"]
    if weekday >= 5:
        start = options.get("weekend_schedule_start", start)
        end = options.get("weekend_schedule_end", end)
    return time.fromisoformat(start), time.fromisoformat(end)


def inside_weekly_schedule(now, options):
    """Is local wall time within today's or yesterday's started window?

    Overnight windows belong to their starting day. Friday's overnight
    allowance can finish on Saturday, and Sunday's can finish on Monday.
    Compare local clock values to honor DST without inventing elapsed time.
    """
    clock = now.time().replace(tzinfo=None)
    start, end = _schedule_for_weekday(options, now.weekday())
    if start == end:
        return True  # Equal endpoints explicitly mean all-day permission.
    if start < end and start <= clock < end:
        return True
    if start > end and clock >= start:
        return True
    previous_start, previous_end = _schedule_for_weekday(
        options, (now.weekday() - 1) % 7)
    return previous_start > previous_end and clock < previous_end


def violations(options, totals, now, active_games):
    options = DEFAULTS | options
    if not options["enabled"] or options["unlimited"]:
        return []
    limits = [(period, effective_budget_limit(options, now, period)) for period in ("daily", "weekly")]
    reasons = [key for key, limit in limits if limit >= 0 and totals[key] >= limit * 60]
    if options["schedule_enabled"] and not inside_weekly_schedule(now, options):
        reasons.append("schedule")
    for game in sorted(active_games):
        limit = options["per_game"].get(game, -1)
        if limit >= 0 and totals["per_game"].get(game, 0) >= limit * 60:
            reasons.append("game:" + game)
    return reasons


def remaining_budget_percent(options, totals, now, period):
    """Percent of the independently configured daily/weekly quota remaining.

    Unknown when no finite quota applies or accounting is not ready. The
    other quotas and schedule may independently prohibit play.
    """
    if period not in ("daily", "weekly"):
        raise ValueError("Unsupported budget period")
    options = DEFAULTS | options
    if not options["enabled"] or options["unlimited"]:
        return None
    limit = effective_budget_limit(options, now, period)
    if limit < 0 or period not in totals:
        return None
    if limit == 0:
        return 0.0
    return round(100 * max(0.0, min(1.0, 1.0 - totals[period] / (limit * 60))), 1)
