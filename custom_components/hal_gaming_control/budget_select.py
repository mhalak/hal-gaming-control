"""Per-PC native select receipt: inspect allowances or remove an untouched bonus.

The standard HA SelectEntity can only render plain strings. Unicode FIGURE
SPACE keeps the numeric column approximately aligned in proportional fonts,
but it cannot guarantee pixel-perfect right-edge alignment on every client.
Grant IDs always stay internal; identical labels use stable display ordinals.
"""
from collections import Counter
from datetime import datetime, timezone
from math import ceil, floor, isfinite

from homeassistant.util import dt as dt_util

from .parent_bonus import parent_bonus_legacy_today, parent_grants_today, parent_smart_grants
from .smart_policy import effective_snapshot
from .gaming_penalty import active_penalties
from .smart_receipt import smart_receipt
from .rule_engine import budget_overview
from .screen_idle_bonus import screen_idle_events_today

FIGURE_SPACE = "\u2007"
ACTION_GAP = FIGURE_SPACE * 6
# The default selected TOTAL is followed by two read-only usage rows.
TOTAL_ROW_INDEX = -3


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
        if "smart_adjustments" in grant:
            continue
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
    verified = type(used) in (int, float) and isfinite(used) and used >= 0
    played_minutes = ceil(used / 60) if verified else None
    # Minus remains the FIRST character, with one figure-space to the
    # amount column; avoid shifting the minus itself to the right.
    usage = (_amount_label(played_minutes, "Gaming Session", width, sign="−")
             if verified else "− Unknown - Gaming Session")
    if status == "disabled":
        remaining = "∑ Rules Disabled - Remaining Budget"
    elif status == "unlimited":
        remaining = "∑ Unlimited - Remaining Budget"
    elif verified and type(receipt["daily_limit_minutes"]) is int:
        total = receipt["daily_limit_minutes"]
        # A fractional minute of play consumes the next displayed minute;
        # the balance never overstates time available in whole minutes.
        remaining = _amount_label(max(0, total - played_minutes),
                                  "Remaining Budget", width, sign="∑")
    else:
        remaining = "∑ Unknown - Remaining Budget"
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


def budget_select_rows(options, device_id, data, now, *, segments=None):
    """Ordered (label, eligible_grant_id) receipt with exact-second safety.

    Charge base/weekend/legacy first, then oldest active bonus first.
    This is a deterministic attribution convention, *not* proof of which
    real-world gaming minutes consumed which particular bonus.
    """
    data = data or {}
    snapshot = effective_snapshot(options, data.get("totals", {}), now, device_id,
                                  ready=data.get("ready") is True)
    try:
        penalties = active_penalties(options, device_id, now)
    except ValueError:
        return [("∑ Invalid penalty journal - TOTAL", None),
                ("− Unknown - Gaming Session", None),
                ("∑ Unknown - Remaining Budget", None)]
    if options.get("gaming_suspended") is True:
        lines = _penalty_rows(penalties, now, None)
        used = data.get("totals", {}).get("daily")
        usage = (_amount_label(ceil(used / 60), "Gaming Session", 3, sign="−")
                 if data.get("ready") is True and type(used) in (int, float)
                 and isfinite(used) and used >= 0 else "− Unknown - Gaming Session")
        lines.extend([("∑ Gaming suspended - TOTAL", None), (usage, None),
                      (_amount_label(0, "Remaining Budget", 3, sign="∑")
                       if snapshot.selection.status == "limited"
                       else "∑ Unknown - Remaining Budget", None)])
        return _display_action_column(lines)
    if penalties:
        return _penalty_display(options, device_id, data, now, snapshot, segments, penalties)
    has_smart = bool(parent_smart_grants(options, device_id, now)) or any(
        "smart_adjustments" in row for row in parent_grants_today(options, now))
    if has_smart or (snapshot.selection.limiting_sources
                     and snapshot.selection.limiting_sources[0] != "daily"):
        return _smart_display(options, device_id, data, now, snapshot, segments)
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
    rows.extend((_total_row(receipt, width), usage, remaining))
    return _display_action_column(rows)


def _smart_display(options, device_id, data, now, snapshot, segments):
    receipt = smart_receipt(options, data.get("totals", {}), now, device_id, snapshot, segments)
    if receipt is None:
        status = {"disabled": "Rules Disabled", "unlimited": "Unlimited"}.get(
            snapshot.selection.status, "Unknown")
        return [(f"∑{FIGURE_SPACE}{status} - TOTAL", None),
                ("− Unknown - Gaming Session", None),
                (f"∑{FIGURE_SPACE}{status} - Remaining Budget", None)]
    used, remaining = ceil(receipt.used / 60), floor(receipt.remaining / 60)
    total = used + remaining
    amounts = [floor(row.seconds / 60) for row in receipt.lines]
    # Keep the displayed receipt balanced even for fractional-minute grants.
    # Exact seconds stay in the policy; the compensated base absorbs rounding.
    amounts[0] += total - sum(amounts)
    width = max(3, len(str(total)), len(str(used)), *(len(str(abs(n))) for n in amounts))
    rows = []
    has_smart = any("smart_adjustments" in row for row in parent_grants_today(options, now))
    smart_ids = {row["id"] for row in parent_grants_today(options, now)
                 if "smart_intent" in row}
    for line, amount in zip(receipt.lines, amounts):
        grant = line.grant_id
        # Legacy receipts predate captured smart intent. Removing them could
        # invalidate historical base snapshots, so keep them read-only once
        # today's smart grants exist.
        if has_smart and grant not in smart_ids:
            grant = None
        rows.append((_amount_label(abs(amount), line.title, width, sign="−" if amount < 0 else "+"), grant))
    title = "Weekly Gaming Session" if receipt.source == "weekly" else "Gaming Session"
    rows.extend([(_amount_label(total, "TOTAL", width, sign="∑"), None),
                 (_amount_label(used, title, width, sign="−"), None),
                 (_amount_label(remaining, "Remaining Budget", width, sign="∑"), None)])
    return _display_action_column(rows)


def _penalty_rows(penalties, now, remaining):
    """Render independent Undo rows and reconcile conservative display rounding."""
    rows = []
    for index, row in enumerate(penalties, 1):
        clock = datetime.fromisoformat(row["created_at"]).astimezone(now.tzinfo).strftime("%H:%M")
        suffix = f" ({clock} #{index})"
        amount = row["seconds"]
        if remaining is None:
            label = ("Gaming cancelled today" if row["cancel_today"] else
                     _amount_label(ceil(amount / 60), "Gaming Penalty", 3, sign="−"))
        else:
            after = 0 if row["cancel_today"] else max(0, remaining - amount)
            deducted = floor(remaining / 60) - floor(after / 60)
            title = "Gaming cancelled today" if row["cancel_today"] else "Gaming Penalty"
            if not row["cancel_today"] and deducted != ceil(amount / 60):
                title += f" ({ceil(amount / 60)} min assigned)"
            label = _amount_label(deducted, title, 3, sign="−")
            remaining = after
        rows.append((label + suffix, "penalty:" + row["id"]))
    return rows


def _penalty_display(options, device_id, data, now, snapshot, segments, penalties):
    """Keep the base receipt and show today's temporary deductions separately."""
    raw = effective_snapshot(options, data.get("totals", {}), now, device_id,
                             ready=data.get("ready") is True, include_penalties=False)
    selection = snapshot.selection
    if raw.selection.status == "limited" and selection.status == "limited":
        base_rows = _smart_display(options, device_id, data, now, raw, segments)
        receipt = smart_receipt(options, data.get("totals", {}), now, device_id, raw, segments)
        if receipt is not None:
            used = ceil(receipt.used / 60)
            remaining = floor(selection.remaining_seconds / 60)
            lines = [(label.split(ACTION_GAP + "⛔")[0].rstrip(FIGURE_SPACE), grant)
                     for label, grant in base_rows[:-3]]
            lines.extend(_penalty_rows(penalties, now, raw.selection.remaining_seconds))
            lines.extend([(_amount_label(used + remaining, "TOTAL", 3, sign="∑"), None),
                          base_rows[-2],
                          (_amount_label(remaining, "Remaining Budget", 3, sign="∑"), None)])
            return _display_action_column(lines)
    lines = _penalty_rows(penalties, now, None)
    if selection.status == "limited":
        used = data.get("totals", {}).get("daily")
        if type(used) in (int, float) and isfinite(used) and used >= 0:
            played = ceil(used / 60)
            remaining = floor(selection.remaining_seconds / 60)
            lines.extend([(_amount_label(played + remaining, "TOTAL", 3, sign="∑"), None),
                          (_amount_label(played, "Gaming Session", 3, sign="−"), None),
                          (_amount_label(remaining, "Remaining Budget", 3, sign="∑"), None)])
            return _display_action_column(lines)
    status = {"disabled": "Rules Disabled", "unlimited": "Unlimited"}.get(selection.status, "Unknown")
    lines.extend([(f"∑{FIGURE_SPACE}{status} - TOTAL", None),
                  ("− Unknown - Gaming Session", None),
                  (f"∑{FIGURE_SPACE}{status} - Remaining Budget", None)])
    return _display_action_column(lines)
