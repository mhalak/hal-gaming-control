"""Daily, device-local penalties, independent of actual usage and bonus journals."""
from datetime import datetime, timedelta, timezone
from math import isfinite
from uuid import uuid4

KEY = "gaming_penalty_journal"
MAX_EVENTS = 200


def _day(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Penalty requires an aware timestamp")
    return now.date().isoformat()


def _events(options):
    journal = options.get(KEY, {"version": 1, "events": []})
    if not isinstance(journal, dict) or journal.get("version") != 1:
        raise ValueError("Invalid penalty journal")
    rows = journal.get("events")
    if not isinstance(rows, list) or len(rows) > MAX_EVENTS:
        raise ValueError("Invalid penalty records")
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id", "device_id", "date", "created_at", "seconds", "cancel_today", "undone_at"
        }:
            raise ValueError("Invalid penalty record")
        if (not isinstance(row["id"], str) or not row["id"] or row["id"] in ids
                or not isinstance(row["device_id"], str) or not row["device_id"]
                or type(row["cancel_today"]) is not bool
                or type(row["seconds"]) not in (int, float)
                or not isfinite(row["seconds"]) or not 0 <= row["seconds"] <= 36000
                or (row["seconds"] == 0) != row["cancel_today"]):
            raise ValueError("Invalid penalty fields")
        try:
            datetime.strptime(row["date"], "%Y-%m-%d")
            created = datetime.fromisoformat(row["created_at"])
            undone = datetime.fromisoformat(row["undone_at"]) if row["undone_at"] is not None else None
            if created.utcoffset() != timedelta(0) or (undone is not None and
                    (undone.utcoffset() != timedelta(0) or undone < created)):
                raise ValueError("Invalid penalty timestamps")
        except (TypeError, ValueError) as err:
            raise ValueError("Invalid penalty timestamps") from err
        ids.add(row["id"])
    return rows


def active_penalties(options, device_id, now):
    day = _day(now)
    return [dict(row) for row in _events(options)
            if row["device_id"] == device_id and row["date"] == day and row["undone_at"] is None]


def add_penalty(options, device_id, now, *, minutes=None, remaining_seconds=None, cancel_today=False):
    """Return an atomic options candidate. A duplicate full cancellation is a no-op."""
    day = _day(now)
    if not isinstance(device_id, str) or not device_id or type(cancel_today) is not bool:
        raise ValueError("Invalid penalty target")
    if cancel_today:
        if minutes is not None:
            raise ValueError("Choose cancellation or minutes, not both")
        if any(row["cancel_today"] for row in active_penalties(options, device_id, now)):
            return options
        seconds = 0
    else:
        if type(minutes) is not int or not 1 <= minutes <= 600:
            raise ValueError("Penalty must be 1–600 whole minutes")
        if (type(remaining_seconds) not in (int, float) or not isfinite(remaining_seconds)
                or remaining_seconds < 0):
            raise ValueError("Verified finite remaining gaming time required")
        seconds = min(minutes * 60, remaining_seconds)
        if not seconds:
            return options
    cutoff = (now.date() - timedelta(days=7)).isoformat()
    rows = [dict(row) for row in _events(options) if row["date"] >= cutoff]
    if len(rows) >= MAX_EVENTS:
        raise ValueError("Penalty journal is full")
    rows.append({"id": uuid4().hex, "device_id": device_id, "date": day,
                 "created_at": now.astimezone(timezone.utc).isoformat(),
                 "seconds": seconds, "cancel_today": cancel_today, "undone_at": None})
    return dict(options) | {KEY: {"version": 1, "events": rows}}


def undo_penalty(options, device_id, now, penalty_id):
    """Undo one exact current-day penalty, without touching any other record."""
    day = _day(now)
    rows = [dict(row) for row in _events(options)]
    for row in rows:
        if (row["id"] == penalty_id and row["device_id"] == device_id
                and row["date"] == day and row["undone_at"] is None):
            stamp = now.astimezone(timezone.utc)
            if stamp < datetime.fromisoformat(row["created_at"]):
                raise ValueError("Undo precedes penalty")
            row["undone_at"] = stamp.isoformat()
            return dict(options) | {KEY: {"version": 1, "events": rows}}
    raise ValueError("Penalty is no longer active on this PC")


def project_penalties(selection, options, device_id, now, *, ready):
    """Subtract today's deduction from the effective allowance, not raw usage."""
    from .smart_budget import BudgetSelection

    try:
        rows = active_penalties(options, device_id, now)
    except ValueError:
        return BudgetSelection("unknown", {})
    if not rows or not options.get("enabled") or options.get("unlimited"):
        return selection
    if not ready or selection.status == "unknown":
        return BudgetSelection("unknown", {})
    cancel = any(row["cancel_today"] for row in rows)
    if selection.status != "limited" and not cancel:
        return selection
    remaining = 0 if cancel else max(0, selection.remaining_seconds - sum(row["seconds"] for row in rows))
    sources = selection.limiting_sources
    return BudgetSelection("limited", dict(selection.balances) | {"penalty": remaining},
                           remaining, (*sources, "penalty"))
