"""Per-PC native select receipt: inspect allowances or remove an untouched bonus.

The standard HA SelectEntity can only render plain strings. Unicode FIGURE
SPACE keeps the numeric column approximately aligned in proportional fonts,
but it cannot guarantee pixel-perfect right-edge alignment on every client.
Grant IDs always stay internal; identical labels use stable display ordinals.
"""
from collections import Counter
from datetime import datetime, timezone
from math import ceil, isfinite

from homeassistant.util import dt as dt_util

from .parent_bonus import parent_bonus_legacy_today, parent_grants_today
from .rule_engine import budget_overview
from .screen_idle_bonus import screen_idle_events_today

FIGURE_SPACE = "\u2007"
ACTION_GAP = FIGURE_SPACE * 6
# Native select options must have distinct labels; no-op dividers use
# slightly different lengths rather than duplicated option names.
DIVIDER_TOP = "─" * 24
DIVIDER_BOTTOM = "─" * 25


def _amount_label(minutes, title, width, sign="+"):
    """Align numeric amounts without collapsible ASCII whitespace."""
    return (f"{sign}{FIGURE_SPACE}"
            f"{str(minutes).rjust(width, FIGURE_SPACE)} min - {title}")


def _fixed_rows(receipt, options, now, width):
    """Non-revocable base, Weekend and legacy rows and their accumulated pool."""
    base = receipt["base_daily_minutes"]
    rows = [(_amount_label(base, "Daily Budget", width) if base is not None
             else "∞ Daily Budget", None)]
    weekend = receipt["weekend_bonus_minutes"]
    if weekend:
        rows.append((_amount_label(weekend, "Weekend Bonus", width), None))
    legacy = parent_bonus_legacy_today(options, now)
    if legacy:
        rows.append((_amount_label(legacy, "Legacy Parent Bonus", width), None))
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


def _event_labels(events, width):
    """Use human-friendly #1/#2 only for same-minute duplicate labels.

    The exact immutable grant ID remains solely in the paired option value,
    never in the name shown to parents.
    """
    frequencies = Counter(_event_key(event) for event in events)
    seen = Counter()
    labels = []
    for event in events:
        key = _event_key(event)
        kind = "Parent Bonus" if event["kind"] == "parent" else "Screen Off Bonus"
        seen[key] += 1
        disambiguator = f" #{seen[key]}" if frequencies[key] > 1 else ""
        title = f"{kind} ({key[2]}{disambiguator})"
        labels.append(_amount_label(event["minutes"], title, width))
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
    # the current cumulative accounting state. Recheck at instant Undo.
    return (used <= spent_before * 60
            and used <= (total - event["minutes"]) * 60)


def _total_row(receipt, width):
    status, total = receipt["daily_budget_status"], receipt["daily_limit_minutes"]
    if status == "disabled":
        return f"∑{FIGURE_SPACE}Rules Disabled", None
    if total is None:
        return f"∑{FIGURE_SPACE}Unlimited TOTAL", None
    return f"∑{FIGURE_SPACE}{str(total).rjust(width, FIGURE_SPACE)} min - TOTAL", None


def _usage_rows(receipt, width):
    """Read-only, conservative whole-minute snapshot of verified daily usage.

    Never turn missing evidence into zero. Round consumed minutes UP and
    remaining minutes DOWN, without changing the exact-second rule engine.
    This makes the displayed receipt reconcile for a finite daily budget.
    """
    used = receipt["daily_used_seconds"]
    status = receipt["daily_budget_status"]
    if type(used) not in (int, float) or not isfinite(used) or used < 0:
        usage = "- Unknown - Gaming Session"
        remaining = "∑ Unknown - Remaining Budget"
    else:
        usage = _amount_label(ceil(used / 60), "Gaming Session", width, sign="-")
        if status == "disabled":
            remaining = "∑ Rules Disabled - Remaining Budget"
        elif status == "unlimited":
            remaining = "∑ Unlimited - Remaining Budget"
        else:
            remaining_seconds = receipt["daily_remaining_seconds"]
            if remaining_seconds is None:
                remaining = "∑ Unknown - Remaining Budget"
            else:
                # Rule engine returns ceil(seconds left). Floor whole minutes
                # from the displayed seconds, never fabricate free minutes.
                remaining_minutes = remaining_seconds // 60
                remaining = _amount_label(
                    remaining_minutes, "Remaining Budget", width, sign="∑")
    return (usage, None), (remaining, None)


def _display_action_column(rows):
    """Right-align the action glyph within the *text*, not the HA control.

    Only actionable Parent bonuses get the red icon; pad them relative to the
    longest actionable text. Unicode figure spaces aren't collapsed by HTML,
    unlike ordinary multiple spaces. Native HA controls still own actual width.
    """
    longest = max((len(label) for label, grant in rows if grant), default=0)
    return [(label + FIGURE_SPACE * (longest - len(label)) + ACTION_GAP + "⛔",
             grant) if grant else (label, None)
            for label, grant in rows]


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
    events = _bonus_events(options, device_id, now)
    used = receipt["daily_used_seconds"]
    remaining = receipt["daily_remaining_seconds"]
    amounts = [receipt["daily_limit_minutes"], receipt["base_daily_minutes"],
               *(event["minutes"] for event in events)]
    if type(used) in (int, float) and isfinite(used) and used >= 0:
        amounts.append(ceil(used / 60))
    if type(remaining) is int and remaining >= 0:
        amounts.append(remaining // 60)
    width = max(3, *(len(str(amount)) for amount in amounts
                     if isinstance(amount, int)))
    rows, spent_before = _fixed_rows(receipt, options, now, width)
    for event, label in zip(events, _event_labels(events, width)):
        eligible = _can_undo(event, receipt, data, spent_before)
        rows.append((label, event["id"] if eligible else None))
        spent_before += event["minutes"]
    usage, remaining = _usage_rows(receipt, width)
    rows.extend(((DIVIDER_TOP, None), _total_row(receipt, width), usage,
                 (DIVIDER_BOTTOM, None), remaining))
    return _display_action_column(rows)
