"""Persist the original policy inputs needed to replay a parent grant."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .public_holidays import historical_holiday_policy


@dataclass(frozen=True)
class IntentSnapshot:
    at: datetime
    base_balances: dict
    schedule_options: dict | None


def _balances(values):
    if not isinstance(values, dict) or set(values) - {"daily", "weekly"}:
        raise ValueError("Invalid smart bonus base balances")
    if any(type(value) not in (int, float) or not isfinite(value)
           for value in values.values()):
        raise ValueError("Unknown smart bonus base balance")
    return dict(values)


def _schedule(options):
    if options is None:
        return None
    if not isinstance(options, dict):
        raise ValueError("Invalid historical schedule options")
    result = {}
    for key in ("enabled", "unlimited", "schedule_enabled"):
        if type(options.get(key)) is not bool:
            raise ValueError("Invalid historical schedule flag")
        result[key] = options[key]
    for key in ("schedule_start", "schedule_end", "weekend_schedule_start", "weekend_schedule_end"):
        value = options.get(key, result.get(key.removeprefix("weekend_")))
        if not isinstance(value, str) or time.fromisoformat(value).tzinfo is not None:
            raise ValueError("Invalid historical schedule clock")
        result[key] = value
    result.update(historical_holiday_policy(options))
    return result


def capture_intent(at, base_balances, schedule_options=None):
    """Capture only relevant historical inputs, never current usage or credentials."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Grant requires aware timestamp")
    zone = "UTC" if at.tzinfo is timezone.utc else getattr(at.tzinfo, "key", None)
    if not isinstance(zone, str):
        raise ValueError("Grant requires an IANA timezone")
    record = {"version": 1, "at_utc": at.astimezone(timezone.utc).isoformat(),
              "zone": zone, "base_balances": _balances(base_balances),
              "schedule_options": _schedule(schedule_options)}
    read_intent(record)
    return record


def read_intent(record):
    """Restore local calendar semantics, including DST fold, from a UTC instant."""
    if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
        raise ValueError("Invalid smart bonus intent record")
    try:
        instant = datetime.fromisoformat(record["at_utc"])
        if instant.utcoffset() != timedelta(0):
            raise ValueError("Historical grant timestamp must be UTC")
        local = instant.astimezone(ZoneInfo(record["zone"]))
        return IntentSnapshot(local, _balances(record["base_balances"]),
                              _schedule(record["schedule_options"]))
    except (KeyError, TypeError, ZoneInfoNotFoundError) as error:
        raise ValueError("Invalid smart bonus intent record") from error
