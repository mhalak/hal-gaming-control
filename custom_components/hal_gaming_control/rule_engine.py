"""Pure rule evaluation and calendar windows. All timestamps are timezone-aware."""
from datetime import datetime, timedelta, time
from .const import DEFAULTS
from .unlimited_bonus import credit_seconds
from .protocol import games_from_state
from .public_holidays import weekend_equivalent, holiday_receipt


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
    if "parent_bonus_journal" in options:
        from .parent_bonus import parent_bonus_total
        return parent_bonus_total(options, now)
    if options.get("bonus_date") != now.date().isoformat():
        return 0
    value = options.get("bonus_minutes", 0)
    return value if type(value) is int and value >= 0 else 0


def effective_budget_limit(options, now, period, *, device_id=None, totals=None):
    options = DEFAULTS | options
    if device_id is not None:
        from .parent_bonus import parent_smart_grants
        from .smart_policy import quota_limits
        if period not in ("daily", "weekly"):
            raise ValueError("Unsupported budget period")
        _, limits = quota_limits(options, now, parent_smart_grants(options, device_id, now), totals)
        if period not in limits:
            return -1
        minutes = limits[period] / 60
        return int(minutes) if minutes.is_integer() else minutes
    if period == "weekly":
        return options["weekly"]
    if period != "daily":
        raise ValueError("Unsupported budget period")
    base = effective_daily(options, weekend_equivalent(options, now.date()))
    if base < 0:
        return base
    from .screen_idle_bonus import screen_idle_bonus_total
    return base + daily_bonus_minutes(options, now) + screen_idle_bonus_total(options, now)


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


def _schedule_for_date(options, day):
    """Select a window using its starting local date, including public holidays."""
    weekday = 5 if weekend_equivalent(options, day) else day.weekday()
    return _schedule_for_weekday(options, weekday)


def inside_weekly_schedule(now, options):
    """Is local wall time within today's or yesterday's started window?

    Overnight windows belong to their starting day. Friday's overnight
    allowance can finish on Saturday, and Sunday's can finish on Monday.
    Compare local clock values to honor DST without inventing elapsed time.
    """
    clock = now.time().replace(tzinfo=None)
    start, end = _schedule_for_date(options, now.date())
    if start == end:
        return True  # Equal endpoints explicitly mean all-day permission.
    if start < end and start <= clock < end:
        return True
    if start > end and clock >= start:
        return True
    previous_start, previous_end = _schedule_for_date(
        options, now.date() - timedelta(days=1))
    return previous_start > previous_end and clock < previous_end


def violations(options, totals, now, active_games, *, device_id=None):
    options = DEFAULTS | options
    if options["gaming_suspended"]:
        return ["suspended"]
    if not options["enabled"] or options["unlimited"]:
        return []
    if device_id is not None:
        from .smart_policy import effective_snapshot
        snapshot = effective_snapshot(options, totals, now, device_id, ready=True)
        reasons = [key for key, balance in snapshot.selection.balances.items()
                   if balance is not None and balance <= 0]
    else:
        limits = [(period, effective_budget_limit(options, now, period)) for period in ("daily", "weekly")]
        reasons = [key for key, limit in limits if limit >= 0 and totals[key] >= limit * 60]
        if options["schedule_enabled"] and not inside_weekly_schedule(now, options):
            reasons.append("schedule")
    for game in sorted(active_games):
        limit = options["per_game"].get(game, -1)
        if limit >= 0 and totals["per_game"].get(game, 0) - credit_seconds(totals, "per_game", game) >= limit * 60:
            reasons.append("game:" + game)
    return reasons


def remaining_budget_percent(options, totals, now, period, *, device_id=None):
    """Percent of the independently configured daily/weekly quota remaining.

    Unknown when no finite quota applies or accounting is not ready. The
    other quotas and schedule may independently prohibit play.
    """
    if period not in ("daily", "weekly"):
        raise ValueError("Unsupported budget period")
    options = DEFAULTS | options
    if not options["enabled"] or options["unlimited"]:
        return None
    limit = effective_budget_limit(options, now, period, device_id=device_id, totals=totals)
    if limit < 0 or period not in totals:
        return None
    if limit == 0:
        return 0.0
    return round(100 * max(0.0, min(1.0, 1.0 - totals[period] / (limit * 60))), 1)


def _public_grant(row):
    """Keep full historical intent and original adjustment audit out of Recorder."""
    result = {key: value for key, value in row.items()
              if key not in ("smart_intent", "smart_original_adjustments")}
    if row.get("source") == "sync":
        result["minutes"] = row["amount_seconds"] / 60
    return result


def _receipt_status(settings, limit):
    if not settings["enabled"]:
        return "disabled"
    return "unlimited" if settings["unlimited"] or limit < 0 else "limited"


def _receipt_grants(settings, now, device_id):
    from .parent_bonus import grant_seconds, parent_bonus_activity_today, parent_grants_today

    # The full journal belongs to config-entry options, not Recorder attrs.
    # Mirror only the newest entries: 50 active + 50 audit entries can exceed
    # Home Assistant's 16 KiB recorder state-attributes threshold.
    activity = parent_bonus_activity_today(settings, now)
    active_grants = parent_grants_today(settings, now)
    if device_id is not None:
        activity = [row for row in activity if row["device_id"] == device_id]
        active_grants = [row for row in active_grants if row["device_id"] == device_id]
    smart_requested = sum(grant_seconds(row) for row in active_grants
                          if "smart_adjustments" in row) / 60 if device_id is not None else 0
    latest = max(
        activity, key=lambda event: (
            event["cancelled_at_utc"] or event["created_at_utc"]), default=None)
    recent_action = ({
        "action": "cancelled" if latest["status"] == "cancelled" else "added",
        "minutes": grant_seconds(latest) / 60 if latest.get("source") == "sync" else latest["minutes"],
        "at_utc": latest["cancelled_at_utc"] or latest["created_at_utc"],
        "grant_id": latest["id"],
    } if latest else None)
    if latest and latest.get("source") == "sync":
        recent_action["amount_seconds"] = grant_seconds(latest)
        recent_action["source"] = "sync"

    return activity, active_grants, smart_requested, recent_action


def budget_overview(options, totals, now, *, ready, coverage_incomplete=True, device_id=None):
    """Read-only, device-scoped receipt from the same exact-second rule inputs.

    Keep daily bonuses separate; do not rewrite measured time, grant a Screen
    Idle bonus before #92 exists, or report unknown/offline time as zero.
    """
    from math import ceil, floor, isfinite
    from .parent_bonus import (
        parent_bonus_legacy_today,
    )

    from .screen_idle_bonus import screen_idle_bonus_total
    settings = DEFAULTS | options
    base = settings["daily"]
    daily_limit = effective_budget_limit(settings, now, "daily", device_id=device_id, totals=totals)
    weekly_limit = effective_budget_limit(settings, now, "weekly", device_id=device_id, totals=totals)
    daily_status = _receipt_status(settings, daily_limit)
    weekly_status = _receipt_status(settings, weekly_limit)

    def verified_seconds(period):
        seconds = totals.get(period) if ready else None
        if (type(seconds) not in (int, float) or not isfinite(seconds)
                or seconds < 0):
            return None
        return seconds

    def whole_hundredths(seconds):
        # For display only; never round played time UP to an enforcement boundary.
        return floor(seconds / 60 * 100) / 100 if seconds is not None else None

    def remaining_seconds(limit, used):
        if limit is None or used is None:
            return None
        # 0.1 second left still means gaming time remains. The underlying
        # enforcement uses unrounded seconds, not this display countdown.
        return ceil(max(0, limit * 60 - used))

    activity, active_grants, smart_requested, recent_action = _receipt_grants(settings, now, device_id)

    daily_used = verified_seconds("daily")
    weekly_used = verified_seconds("weekly")
    daily_finite = daily_limit if daily_status == "limited" else None
    weekly_finite = weekly_limit if weekly_status == "limited" else None
    daily_left = remaining_seconds(daily_finite, daily_used)
    weekly_left = remaining_seconds(weekly_finite, weekly_used)
    return {
        "unlimited_gaming_active": bool(settings["unlimited"]),
        "daily_budget_status": daily_status,
        "weekly_budget_status": weekly_status,
        "base_daily_minutes": base if base >= 0 else None,
        "weekend_bonus_minutes": (
            _validated_weekend_bonus(settings.get("weekend_bonus", 0))
            if base >= 0 and weekend_equivalent(settings, now.date()) else 0),
        "parent_bonus_minutes": daily_bonus_minutes(settings, now) + smart_requested,
        "parent_bonus_legacy_minutes": parent_bonus_legacy_today(settings, now),
        "parent_bonus_grants_today": [_public_grant(row) for row in active_grants[:12]],
        "parent_bonus_activity_today": [_public_grant(row) for row in activity[:12]],
        "parent_bonus_recent_action": recent_action,
        "screen_idle_bonus_minutes": screen_idle_bonus_total(settings, now),
        "screen_idle_bonus_status": "automatic",
        "daily_limit_minutes": daily_finite,
        "daily_unlimited_bonus_seconds": credit_seconds(totals, "daily") if ready else None,
        "weekly_unlimited_bonus_seconds": credit_seconds(totals, "weekly") if ready else None,
        "daily_used_seconds": daily_used,
        "daily_used_minutes": whole_hundredths(daily_used),
        "daily_remaining_seconds": daily_left,
        "daily_remaining_minutes": whole_hundredths(daily_left),
        "weekly_limit_minutes": weekly_finite,
        "weekly_used_seconds": weekly_used,
        "weekly_used_minutes": whole_hundredths(weekly_used),
        "weekly_remaining_seconds": weekly_left,
        "weekly_remaining_minutes": whole_hundredths(weekly_left),
        "coverage_incomplete": bool(coverage_incomplete),
        **holiday_receipt(settings, now.date()),
    }
