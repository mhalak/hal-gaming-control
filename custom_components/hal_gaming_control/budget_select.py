"""Plain-text, read-only gaming allowance receipt for the native HA select.

Home Assistant SelectEntity does not support disabled individual options. The
lock glyph is explanatory; the service layer must reject locked selections.
"""
from collections import Counter
from datetime import datetime, timezone
from math import isfinite

from homeassistant.util import dt as dt_util

from .parent_bonus import parent_bonus_legacy_today, parent_grants_today
from .rule_engine import budget_overview
from .screen_idle_bonus import screen_idle_events_today


def _fixed_rows(receipt, options, now):
    """Non-revocable base, Weekend and legacy rows and their accumulated pool."""
    base = receipt["base_daily_minutes"]
    rows = [(f"🔒 +{base}min Daily budget" if base is not None
             else "🔒 Unlimited Daily budget", None)]
    weekend = receipt["weekend_bonus_minutes"]
    if weekend:
        rows.append((f"🔒 +{weekend}min Weekend bonus", None))
    legacy = parent_bonus_legacy_today(options, now)
    if legacy:
        rows.append((f"🔒 +{legacy}min Legacy Parent bonus", None))
    return rows, (base or 0) + weekend + legacy


def _bonus_events(options, device_id, now):
    """All active current-day bonus receipts, sorted by actual event time."""
    events = []
    for grant in parent_grants_today(options, now):
        events.append({
            "kind": "parent",
            "at": datetime.fromisoformat(grant["created_at_utc"]),
            "minutes": grant["minutes"], "id": grant["id"],
        })
    for grant in screen_idle_events_today(options, now, device_id):
        events.append({
            "kind": "screen",
            "at": datetime.fromtimestamp(grant["off_at_utc"], timezone.utc),
            "minutes": grant["minutes"], "id": grant["id"],
        })
    return sorted(events, key=lambda row: (row["at"], row["kind"], row["id"]))


def _event_key(event):
    return (event["kind"], event["minutes"],
            dt_util.as_local(event["at"]).strftime("%H:%M"))


def _event_labels(events):
    """Disambiguate only otherwise identical human-readable bonus labels."""
    frequencies = Counter(_event_key(event) for event in events)
    short_ids = Counter(
        (_event_key(event), event["id"][-10:]) for event in events
        if event["kind"] == "parent")
    seen_screen = Counter()
    labels = []
    for event in events:
        key = _event_key(event)
        name = "Parent bonus" if event["kind"] == "parent" else "Screen off bonus"
        label = f'+{event["minutes"]}min {name} ({key[2]})'
        if frequencies[key] > 1:
            if event["kind"] == "parent":
                suffix = event["id"][-10:]
                if short_ids[(key, suffix)] > 1:
                    suffix = event["id"]
                label += f" ({suffix})"
            else:
                seen_screen[key] += 1
                label += f" (#{seen_screen[key]})"
        labels.append(label)
    return labels


def _can_undo(event, receipt, data, spent_before):
    """Exact-second policy: an untouched Parent grant can only be removed whole."""
    if event["kind"] != "parent" or data.get("ready") is not True:
        return False
    used = receipt["daily_used_seconds"]
    total = receipt["daily_limit_minutes"]
    if (receipt["daily_budget_status"] != "limited"
            or type(used) not in (int, float) or not isfinite(used)
            or used < 0 or type(total) is not int or total < 0):
        return False
    # The first second attributed to this grant locks it permanently for
    # the current cumulative accounting state. Recheck at Confirm Undo.
    return (used <= spent_before * 60
            and used <= (total - event["minutes"]) * 60)


def _total_row(receipt):
    status, total = receipt["daily_budget_status"], receipt["daily_limit_minutes"]
    if status == "disabled":
        return "🔒 Rules disabled", None
    if total is None:
        return "🔒 Unlimited TOTAL", None
    return f"🔒 {total}min TOTAL", None


def budget_select_rows(options, device_id, data, now):
    """Ordered (label, eligible_grant_id) receipt with exact-second safety.

    Charge base/weekend/legacy first, then oldest active bonus first.
    This is a deterministic attribution convention, *not* proof of which
    real-world gaming minutes consumed which particular bonus.
    """
    data = data or {}
    receipt = budget_overview(
        options, data.get("totals", {}), now, ready=bool(data.get("ready")),
        coverage_incomplete=data.get("coverage_incomplete", True))
    rows, spent_before = _fixed_rows(receipt, options, now)
    events = _bonus_events(options, device_id, now)
    for event, label in zip(events, _event_labels(events)):
        eligible = _can_undo(event, receipt, data, spent_before)
        rows.append((label if eligible else f"🔒 {label}",
                     event["id"] if eligible else None))
        spent_before += event["minutes"]
    rows.append(_total_row(receipt))
    return rows
