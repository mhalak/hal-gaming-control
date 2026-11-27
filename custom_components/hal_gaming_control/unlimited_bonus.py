"""Verified Unlimited interval journal and credit projection."""
from datetime import datetime, time, timedelta
from math import isfinite

KEY = "unlimited_bonus_journal"
MAX_INTERVALS = 2048
MAX_TIMESTAMP = 253402300799


def _timestamp(value):
    if (type(value) not in (int, float) or not isfinite(value)
            or not 0 <= value <= MAX_TIMESTAMP):
        raise ValueError("Invalid Unlimited timestamp")
    return value


def _instant(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Unlimited accounting needs an aware timestamp")
    return _timestamp(now.timestamp())


def _journal(options, device_id):
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("Invalid Unlimited device")
    journal = options.get(KEY, {"version": 1, "device_id": device_id, "intervals": []})
    if (not isinstance(journal, dict)
            or set(journal) != {"version", "device_id", "intervals"}
            or type(journal["version"]) is not int or journal["version"] != 1
            or journal["device_id"] != device_id
            or not isinstance(journal["intervals"], list)
            or len(journal["intervals"]) > MAX_INTERVALS):
        raise ValueError("Invalid Unlimited journal")
    return _validate_intervals(journal["intervals"])


def _validate_intervals(rows):
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("Invalid Unlimited interval")
        start, end = _timestamp(row[0]), row[1]
        if end is not None and _timestamp(end) < start:
            raise ValueError("Unlimited interval ends before start")
        if result and (result[-1][1] is None or result[-1][1] > start):
            raise ValueError("Overlapping Unlimited intervals")
        result.append([start, end])
    return result


def record_override(options, device_id, now, enabled):
    """Build one options candidate; caller commits it atomically with the switch.

    An existing pre-feature Unlimited switch without a journal earns nothing
    retroactively. Recording ON begins at the explicit observation instant.
    """
    if type(enabled) is not bool:
        raise ValueError("Unlimited requires a boolean")
    stamp = _instant(now)
    rows = _journal(options, device_id)
    active = bool(rows and rows[-1][1] is None)
    if rows:
        latest = rows[-1][0] if active else rows[-1][1]
        if stamp < latest:
            raise ValueError("Unlimited transition moved backwards")
    if active == enabled:
        return options
    if enabled:
        # Retain more than a full local week, including DST and calendar shifts.
        cutoff = stamp - 15 * 86400
        rows = [row for row in rows if row[1] is None or row[1] >= cutoff]
        if len(rows) >= MAX_INTERVALS:
            raise ValueError("Unlimited journal is full")
        rows.append([stamp, None])
    else:
        rows[-1][1] = stamp
    return dict(options) | {KEY: {"version": 1, "device_id": device_id, "intervals": rows}}


def _segments(rows):
    previous = 0
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise ValueError("Invalid confirmed game segment")
        start, end, key = row
        if (_timestamp(start) < previous or _timestamp(end) <= start
                or not isinstance(key, str) or not key):
            raise ValueError("Invalid or overlapping confirmed game segments")
        previous = end
        yield start, end, key


def _overlap_segments(intervals, segments, end):
    """Linear sweep of ordered, nonoverlapping intervals and confirmed usage."""
    index = 0
    for first, last, key in _segments(segments):
        while index < len(intervals):
            start, stop = intervals[index]
            stop = min(stop if stop is not None else end, end)
            if stop <= first:
                index += 1
                continue
            if start >= last:
                break
            left, right = max(start, first), min(stop, last)
            if right > left:
                yield left, right, key
            if stop > last:
                break
            index += 1


def unlimited_credits(options, device_id, now, segments):
    """Credit only verified gameplay inside recorded Unlimited intervals.

    Daily and weekly are independent local-calendar windows; per-game is
    today's raw stable-key credit. Missing telemetry is never extrapolated.
    Invalid journals/segments raise rather than awarding fabricated time.
    """
    end = _instant(now)
    day = now.date()
    midnight = datetime.combine(day, time.min, tzinfo=now.tzinfo).timestamp()
    monday = datetime.combine(day - timedelta(days=day.weekday()),
                              time.min, tzinfo=now.tzinfo).timestamp()
    intervals = _journal(options, device_id)
    result = {"daily": 0, "weekly": 0, "per_game": {}}
    for first, last, key in _overlap_segments(intervals, segments, end):
        result["weekly"] += max(0, last - max(first, monday))
        daily = max(0, last - max(first, midnight))
        if daily:
            result["daily"] += daily
            result["per_game"][key] = result["per_game"].get(key, 0) + daily
    return result


def credit_seconds(totals, period, game=None):
    """Read an authoritative credit, never more than the measured usage."""
    credits = totals.get("unlimited_bonus", {})
    if not isinstance(credits, dict):
        return 0
    used, credit = totals.get(period), credits.get(period, 0)
    if game is not None:
        used = used.get(game) if isinstance(used, dict) else None
        credit = credit.get(game, 0) if isinstance(credit, dict) else 0
    if (type(used) not in (int, float) or type(credit) not in (int, float)
            or not isfinite(used) or not isfinite(credit)
            or used < 0 or credit < 0 or credit > used):
        return 0
    return credit


def override_options(options, device_id, now, key, enabled):
    """Atomic policy + journal candidate, including suspension ending Unlimited."""
    updated = dict(options)
    updated[key] = enabled
    if key == "gaming_suspended" and enabled:
        updated["unlimited"] = False
    if key == "unlimited" or (key == "gaming_suspended" and enabled):
        updated = record_override(updated, device_id, now, bool(updated.get("unlimited")))
    return updated


def excluded_seconds(options, device_id, first, last):
    """Seconds of one verified segment already eligible for Unlimited credit."""
    return sum(right - left for left, right, _ in _overlap_segments(
        _journal(options, device_id), ((first, last, "screen"),), last))
