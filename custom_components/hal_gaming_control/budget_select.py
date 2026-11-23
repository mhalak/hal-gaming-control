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


def budget_select_rows(options, device_id, data, now):
    """Ordered (label, eligible_grant_id) rows, with exact-second safety.

    Usage is allocated against the base/weekend/legacy allowance first, then
    chronologically across the bonus events. Only a completely untouched Parent
    grant can be revoked, and only if removing it leaves used <= new limit.
    This allocation is an *accounting convention*, not proof of which
    particular minutes the child consumed.
    """
    data = data or {}
    receipt = budget_overview(
        options, data.get("totals", {}), now, ready=bool(data.get("ready")),
        coverage_incomplete=data.get("coverage_incomplete", True))
    base = receipt["base_daily_minutes"]
    status = receipt["daily_budget_status"]
    total = receipt["daily_limit_minutes"]
    used = receipt["daily_used_seconds"]
    verified = (data.get("ready") is True and status == "limited"
                and type(used) in (int, float) and isfinite(used) and used >= 0
                and type(total) is int and total >= 0)

    rows = []
    rows.append((f"🔒 +{base}min Daily budget" if base is not None
                 else "🔒 Unlimited Daily budget", None))
    weekend = receipt["weekend_bonus_minutes"]
    if weekend:
        rows.append((f"🔒 +{weekend}min Weekend bonus", None))
    legacy = parent_bonus_legacy_today(options, now)
    if legacy:
        rows.append((f"🔒 +{legacy}min Legacy Parent bonus", None))

    events = []
    for grant in parent_grants_today(options, now):
        instant = datetime.fromisoformat(grant["created_at_utc"])
        events.append({
            "kind": "parent", "at": instant, "minutes": grant["minutes"],
            "id": grant["id"],
        })
    for grant in screen_idle_events_today(options, now, device_id):
        instant = datetime.fromtimestamp(grant["off_at_utc"], timezone.utc)
        events.append({
            "kind": "screen", "at": instant, "minutes": grant["minutes"],
            "id": grant["id"],
        })
    events.sort(key=lambda row: (row["at"], row["kind"], row["id"]))

    # Disambiguate same-minute, same-source bonuses deterministically.
    def display_key(event):
        return (event["kind"], event["minutes"],
                dt_util.as_local(event["at"]).strftime("%H:%M"))
    frequencies = Counter(display_key(event) for event in events)
    short_ids = Counter(
        (display_key(event), event["id"][-10:]) for event in events
        if event["kind"] == "parent")
    seen_screen = Counter()
    spent_before = (base or 0) + weekend + legacy
    for event in events:
        clock = dt_util.as_local(event["at"]).strftime("%H:%M")
        kind = event["kind"]
        name = "Parent bonus" if kind == "parent" else "Screen off bonus"
        label = f'+{event["minutes"]}min {name} ({clock})'
        if frequencies[display_key(event)] > 1:
            if kind == "parent":
                suffix = event["id"][-10:]
                if short_ids[(display_key(event), suffix)] > 1:
                    suffix = event["id"]
                label += f" ({suffix})"
            else:
                seen_screen[display_key(event)] += 1
                label += f' (#{seen_screen[display_key(event)]})'

        # Even one second inside this grant makes it irrevocable.
        unused = verified and used <= spent_before * 60
        # It must also be safe when OTHER later bonuses are still available.
        within_remaining = verified and used <= (total - event["minutes"]) * 60
        can_undo = kind == "parent" and unused and within_remaining
        rows.append((label if can_undo else f"🔒 {label}",
                     event["id"] if can_undo else None))
        spent_before += event["minutes"]

    if status == "disabled":
        total_text = "Rules disabled"
    elif total is None:
        total_text = "Unlimited TOTAL"
    else:
        total_text = f"{total}min TOTAL"
    rows.append((f"🔒 {total_text}", None))
    return rows
