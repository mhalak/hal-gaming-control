"""JSON-safe per-grant adjustments, independent of HA runtime or usage."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite


@dataclass(frozen=True)
class ActiveAdjustments:
    daily_seconds: int | float = 0
    weekly_seconds: int | float = 0
    schedule_start: datetime | None = None
    schedule_end: datetime | None = None


def _utc(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Smart bonus requires an aware datetime")
    return now.astimezone(timezone.utc)


def _seconds(value):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError("Invalid smart bonus adjustment seconds")
    return value


def _monday(day):
    return day - timedelta(days=day.weekday())


def make_adjustments(now, extensions, *, schedule_anchor=None):
    """Store only this grant's added interval, not a cumulative schedule window."""
    granted = _utc(now)
    if set(extensions) - {"daily", "weekly", "schedule"}:
        raise ValueError("Unknown smart bonus adjustment")
    daily, weekly, schedule = (_seconds(extensions.get(key, 0))
                               for key in ("daily", "weekly", "schedule"))
    if bool(schedule) != (schedule_anchor is not None):
        raise ValueError("Schedule adjustment requires its original anchor")
    start = _utc(schedule_anchor) if schedule_anchor is not None else None
    if start is not None and start < granted:
        raise ValueError("Schedule adjustment cannot start in the past")
    end = start + timedelta(seconds=schedule) if start is not None else None
    return {"version": 1, "granted_at_utc": granted.isoformat(),
            "day": now.date().isoformat(), "week": _monday(now.date()).isoformat(),
            "daily_seconds": daily, "weekly_seconds": weekly,
            "schedule_start_utc": start.isoformat() if start is not None else None,
            "schedule_end_utc": end.isoformat() if end is not None else None}


def _parse_utc(value):
    if not isinstance(value, str):
        raise ValueError("Invalid smart bonus timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Smart bonus timestamp must be UTC")
    return parsed


def _read_schedule(record, granted):
    start, end = record.get("schedule_start_utc"), record.get("schedule_end_utc")
    if start is None and end is None:
        return None, None
    start, end = _parse_utc(start), _parse_utc(end)
    if not granted <= start < end:
        raise ValueError("Invalid smart bonus schedule interval")
    return start, end


def active_adjustments(record, now):
    """Project an uncancelled record without extending or restarting its clocks."""
    current = _utc(now)
    if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
        raise ValueError("Invalid smart bonus adjustment record")
    try:
        granted = _parse_utc(record["granted_at_utc"])
        day, week = date.fromisoformat(record["day"]), date.fromisoformat(record["week"])
        daily, weekly = _seconds(record["daily_seconds"]), _seconds(record["weekly_seconds"])
    except (KeyError, TypeError) as error:
        raise ValueError("Invalid smart bonus adjustment record") from error
    if _monday(day) != week:
        raise ValueError("Invalid smart bonus week")
    start, end = _read_schedule(record, granted)
    if current < granted:
        return ActiveAdjustments()
    if end is not None and current >= end:
        start = end = None
    return ActiveAdjustments(daily if now.date() == day else 0,
                             weekly if _monday(now.date()) == week else 0, start, end)
