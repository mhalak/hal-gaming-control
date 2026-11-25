"""Persistent, auditable, device-scoped Parent bonus grants.

Version 1 of the journal lives inside the HA config-entry options, retaining
the existing bonus_date/bonus_minutes as a compatibility mirror. It never
touches measured gaming time or Windows/MQTT.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import secrets

from .smart_bonus_record import active_adjustments, make_adjustments

JOURNAL_KEY = "parent_bonus_journal"
JOURNAL_VERSION = 1
RETENTION_DAYS = 90
MAX_EVENTS = 2048


def _legacy(options):
    date = options.get("bonus_date")
    amount = options.get("bonus_minutes", 0)
    if (not isinstance(date, str) and date is not None
            or type(amount) is not int or amount < 0):
        raise ValueError("Invalid legacy Parent bonus")
    return {"date": date, "minutes": amount}


def _validate_event(event):
    if (not isinstance(event, dict)
            or not isinstance(event.get("id"), str)
            or not isinstance(event.get("device_id"), str)
            or not isinstance(event.get("local_date"), str)
            or not isinstance(event.get("created_at_utc"), str)
            or type(event.get("minutes")) is not int
            or event["minutes"] <= 0
            or event.get("status") not in ("active", "cancelled")):
        raise ValueError("Invalid Parent bonus journal record")
    cancelled_at = event.get("cancelled_at_utc")
    if event["status"] == "cancelled" and not isinstance(cancelled_at, str):
        raise ValueError("Invalid Parent bonus cancellation timestamp")
    if event["status"] == "active" and cancelled_at is not None:
        raise ValueError("Invalid active Parent bonus cancellation state")


    if "smart_adjustments" in event:
        _validate_smart_event(event)


def _validate_smart_event(event):
    record = event["smart_adjustments"]
    if (not isinstance(record, dict)
            or record.get("day") != event["local_date"]
            or record.get("granted_at_utc") != event["created_at_utc"]):
        raise ValueError("Smart bonus adjustment does not match grant")
    active_adjustments(record, datetime.fromisoformat(event["created_at_utc"]))


def _journal(options):
    stored = options.get(JOURNAL_KEY)
    if stored is None:
        return {"version": JOURNAL_VERSION,
                "legacy": _legacy(options), "events": []}
    if (not isinstance(stored, dict)
            or stored.get("version") != JOURNAL_VERSION
            or not isinstance(stored.get("legacy"), dict)
            or not isinstance(stored.get("events"), list)):
        raise ValueError("Invalid Parent bonus journal")
    legacy = dict(stored["legacy"])
    if (legacy.get("date") is not None and not isinstance(legacy["date"], str)
            or type(legacy.get("minutes")) is not int
            or legacy["minutes"] < 0):
        raise ValueError("Invalid Parent bonus journal legacy record")
    events = stored["events"]
    if len(events) > MAX_EVENTS:
        raise ValueError("Parent bonus journal exceeds limit")
    seen = set()
    for event in events:
        _validate_event(event)
        if event["id"] in seen:
            raise ValueError("Duplicate Parent bonus journal ID")
        seen.add(event["id"])
    return {"version": JOURNAL_VERSION, "legacy": legacy,
            "events": deepcopy(events)}


def _date(now):
    # Read-only HA date snapshots may come from tests or restored local clocks.
    # They do not create an audit timestamp; never reinterpret their zone.
    return now.date().isoformat()


def _timestamp(now):
    # A NEW audit mutation always requires a real timezone-aware instant.
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Parent bonus mutation requires timezone-aware clock")
    return now.astimezone(timezone.utc).isoformat()


def parent_bonus_total(options, now):
    """Legacy daily-only total; smart adjustments are projected separately."""
    date = _date(now)
    journal = _journal(options)
    legacy = journal["legacy"]
    total = legacy["minutes"] if legacy["date"] == date else 0
    total += sum(event["minutes"] for event in journal["events"]
                 if event["local_date"] == date and event["status"] == "active"
                 and "smart_adjustments" not in event)
    return total


def parent_grants_today(options, now):
    """A serializable read-only snapshot, newest grant first."""
    date = _date(now)
    journal = _journal(options)
    return list(reversed([dict(event) for event in journal["events"]
                          if event["local_date"] == date
                          and event["status"] == "active"]))


def parent_bonus_activity_today(options, now):
    """All current-day grants, including cancelled audit records."""
    date = _date(now)
    return list(reversed([dict(event) for event in _journal(options)["events"]
                          if event["local_date"] == date]))


def parent_bonus_legacy_today(options, now):
    """Existing unattributed aggregate; not a fabricated clickable grant."""
    legacy = _journal(options)["legacy"]
    return legacy["minutes"] if legacy["date"] == _date(now) else 0


def _write(options, journal, now):
    updated = dict(options)
    updated[JOURNAL_KEY] = journal
    updated["bonus_date"] = _date(now)
    updated["bonus_minutes"] = parent_bonus_total(updated, now)
    return updated


def add_parent_grant(options, device_id, now, amount_minutes=30):
    """Pure atomic mutation candidate; caller commits options synchronously."""
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("Invalid Parent bonus device")
    if type(amount_minutes) is not int or not 0 < amount_minutes <= 600:
        raise ValueError("Invalid Parent bonus minutes")
    date = _date(now)
    journal = _journal(options)
    cutoff = (now.date() - timedelta(days=RETENTION_DAYS)).isoformat()
    journal["events"] = [row for row in journal["events"]
                         if row["local_date"] >= cutoff
                         or "smart_adjustments" in row]
    if len(journal["events"]) >= MAX_EVENTS:
        raise ValueError("Parent bonus journal is full")
    journal["events"].append({
        "id": secrets.token_hex(16),
        "device_id": device_id,
        "local_date": date,
        "created_at_utc": _timestamp(now),
        "minutes": amount_minutes,
        "status": "active",
        "cancelled_at_utc": None,
    })
    return _write(options, journal, now)


def revoke_parent_grant(options, device_id, grant_id, now):
    """Revoke only a verified active grant from this device and local date."""
    date = _date(now)
    journal = _journal(options)
    event = next((entry for entry in journal["events"]
                  if entry["id"] == grant_id), None)
    if event is None:
        raise ValueError("Unknown Parent bonus grant")
    if event["device_id"] != device_id:
        raise ValueError("Parent bonus grant belongs to another device")
    if event["local_date"] != date:
        raise ValueError("Parent bonus grant expired")
    if event["status"] == "cancelled":
        raise ValueError("Parent bonus grant already cancelled")
    event["status"] = "cancelled"
    event["cancelled_at_utc"] = _timestamp(now)
    return _write(options, journal, now)


def add_smart_parent_grant(options, device_id, now, amount_minutes, extensions,
                           *, schedule_anchor=None):
    """Prepare one smart grant; no production caller until policy cutover."""
    record = make_adjustments(now, extensions, schedule_anchor=schedule_anchor)
    updated = add_parent_grant(options, device_id, now, amount_minutes)
    journal = updated[JOURNAL_KEY]
    journal["events"][-1]["smart_adjustments"] = record
    return _write(updated, journal, now)


def parent_smart_grants(options, device_id, now):
    """Return still-effective adjustments by ID, including earlier days this week."""
    active = {}
    for event in _journal(options)["events"]:
        if (event["device_id"] != device_id or event["status"] != "active"
                or "smart_adjustments" not in event):
            continue
        adjustment = active_adjustments(event["smart_adjustments"], now)
        if adjustment.daily_seconds or adjustment.weekly_seconds or adjustment.schedule_end:
            active[event["id"]] = adjustment
    return active
