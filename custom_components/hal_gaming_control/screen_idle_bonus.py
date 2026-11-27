"""HA-local, idempotent Screen idle bonus receipts for verified #92 events.

Never changes measured usage. The bonus is a distinct *daily* allowance,
never a weekly extension. Active automatically for validated telemetry on each PC.
"""
from datetime import datetime, timedelta, timezone
import math
import re

from .unlimited_bonus import excluded_seconds

KEY = "screen_idle_bonus_journal"
MAX_EVENTS = 2048
RETENTION_DAYS = 90
MAX_DAILY_MINUTES = 180
MAX_PER_EVENT_MINUTES = 120
_EVENT_EPOCH = re.compile(r"[0-9a-f]{32}")


def _validate_event(event, seen):
    if (not isinstance(event, dict) or event.keys() != {
            "id", "date", "minutes", "off_at_utc"}
            or not isinstance(event["id"], str)
            or not isinstance(event["date"], str)
            or type(event["minutes"]) is not int
            or not 0 < event["minutes"] <= MAX_PER_EVENT_MINUTES
            or type(event["off_at_utc"]) not in (int, float)
            or not math.isfinite(event["off_at_utc"])
            or not 0 <= event["off_at_utc"] <= 253402300799
            or event["id"] in seen):
        raise ValueError("Corrupt Screen idle bonus event")
    seen.add(event["id"])


def _journal(options, device_id):
    value = options.get(KEY)
    if value is None:
        return {"version": 1, "device_id": device_id, "events": []}
    if (not isinstance(value, dict) or value.keys() != {
            "version", "device_id", "events"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["device_id"] != device_id
            or not isinstance(value["events"], list)
            or len(value["events"]) > MAX_EVENTS):
        raise ValueError("Invalid Screen idle bonus journal")
    seen = set()
    for event in value["events"]:
        _validate_event(event, seen)
    return {"version": 1, "device_id": device_id,
            "events": [dict(event) for event in value["events"]]}


def screen_idle_bonus_total(options, now, device_id=None):
    """Read-only current-day bonus; missing or invalid evidence yields zero."""
    journal = options.get(KEY)
    if journal is None:
        return 0
    try:
        device_id = device_id or journal.get("device_id")
        rows = _journal(options, device_id)["events"]
        return min(MAX_DAILY_MINUTES, sum(
            row["minutes"] for row in rows if row["date"] == now.date().isoformat()))
    except (ValueError, AttributeError, TypeError):
        return 0  # Never expand allowances from corrupted state.


def screen_idle_events_today(options, now, device_id):
    """Read-only verified per-event Screen idle grants for budget receipts.

    Only validated, same-local-day events are returned. A corrupt/missing
    journal must not invent a bonus or grant an Undo opportunity.
    """
    try:
        rows = _journal(options, device_id)["events"]
        today = now.date().isoformat()
        return [row for row in rows if row["date"] == today]
    except (ValueError, TypeError, AttributeError):
        return []


def _verified_minutes(row, segments, now, options=None, device_id=None):
    """Require a continuous, measured tracked-game interval since last input."""
    if now.tzinfo is None or now.utcoffset() is None:
        return 0
    observed = row["observed_at"]
    off = observed - row["display_event_age_ms"] / 1000
    idle = row["last_input_idle_ms"]
    source = row["power_source"]
    timeout = row["ac_timeout_seconds"] if source == "ac" else (
        row["dc_timeout_seconds"] if source == "battery" else None)
    if (type(idle) is not int or type(timeout) is not int
            or not 60 <= timeout <= 7200 or not timeout * 1000 - 5000 <= idle
            or idle > (timeout + 90) * 1000):
        return 0
    start = observed - idle / 1000
    # A disconnected/replayed OFF or clock skew must never grant time.
    if not 0 <= start < off <= now.timestamp() + 2:
        return 0
    from homeassistant.util import dt as dt_util
    off_date = dt_util.as_local(datetime.fromtimestamp(off, timezone.utc)).date()
    start_date = dt_util.as_local(datetime.fromtimestamp(start, timezone.utc)).date()
    if off_date != now.date() or start_date != off_date:
        return 0  # Midnight/DST crossing needs a full split journal; fail closed.
    cursor, measured = start, 0.0
    for first, last, _key in segments:
        if last <= start or first >= off:
            continue
        if first > cursor + 3:
            return 0  # Missing foreground samples; never manufacture idle.
        left, right = max(first, cursor, start), min(last, off)
        if right > left:
            measured += right - left
            if options is not None:
                measured -= excluded_seconds(options, device_id, left, right)
            cursor = right
    if cursor < off - 3:
        return 0
    return min(MAX_PER_EVENT_MINUTES, int(measured // 60))


def maybe_add_screen_idle_grant(options, device_id, row, segments, now):
    """Pure synchronous mutation; replays return the original options.

    Only call after a fresh, verified ON->OFF edge with the matching helper
    epoch/sequence. The caller atomically commits via HA config-entry options.
    """
    if (not isinstance(device_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device_id)
            or row.get("device_id") != device_id
            or row.get("display_state") != "off"
            or row.get("display_scope") != "windows_console"):
        return options
    epoch, seq = row.get("display_epoch"), row.get("display_sequence")
    if (type(epoch) is not str or _EVENT_EPOCH.fullmatch(epoch) is None
            or type(seq) is not int or seq < 1):
        return options
    journal = _journal(options, device_id)
    event_id = f"{epoch}:{seq}"
    if any(event["id"] == event_id for event in journal["events"]):
        return options
    count = _verified_minutes(row, segments, now, options, device_id)
    current = screen_idle_bonus_total(options, now, device_id)
    count = min(count, MAX_DAILY_MINUTES - current)
    if count < 1:
        return options
    cutoff = (now.date() - timedelta(days=RETENTION_DAYS)).isoformat()
    journal["events"] = [event for event in journal["events"]
                         if event["date"] >= cutoff]
    if len(journal["events"]) >= MAX_EVENTS:
        return options
    off = row["observed_at"] - row["display_event_age_ms"] / 1000
    journal["events"].append({
        "id": event_id, "date": now.date().isoformat(),
        "minutes": count, "off_at_utc": off,
    })
    return dict(options, **{KEY: journal})
