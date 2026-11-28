"""Read-only, device-local entitlement comparison for planned bonus sync.

No live service, button, journal mutation or automatic policy change.
"""
from .parent_bonus import _journal as parent_journal, grant_seconds
from .screen_idle_bonus import _journal as screen_journal, MAX_DAILY_MINUTES

MAX_SYNC_SECONDS = 600 * 60


def bonus_entitlement_seconds(options, device_id, now):
    """Count original active discretionary grants, never their projections."""
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("Invalid bonus sync device")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Bonus sync requires an aware date")
    day = now.date().isoformat()
    parent = parent_journal(options)
    rows = parent["events"]
    if any(row["device_id"] != device_id for row in rows):
        raise ValueError("Foreign Parent bonus journal record")
    legacy = parent["legacy"]
    seconds = legacy["minutes"] * 60 if legacy["date"] == day else 0
    seconds += sum(grant_seconds(row) for row in rows
                   if row["local_date"] == day and row["status"] == "active")
    screen = screen_journal(options, device_id)
    seconds += 60 * min(MAX_DAILY_MINUTES, sum(
        row["minutes"] for row in screen["events"] if row["date"] == day))
    return seconds


def sync_difference(target, entitlements):
    """Exact positive top-up; zero for ties, target max, or no peers.

    Values are validated integer seconds, not rounded receipt minutes.
    Refuse an oversized grant rather than partially applying it.
    """
    if not isinstance(entitlements, dict) or target not in entitlements:
        raise ValueError("Missing target bonus entitlement")
    for device, seconds in entitlements.items():
        if (not isinstance(device, str) or not device
                or type(seconds) is not int or seconds < 0):
            raise ValueError("Invalid bonus entitlement")
    difference = max(entitlements.values()) - entitlements[target]
    if difference > MAX_SYNC_SECONDS:
        raise ValueError("Bonus sync difference exceeds maximum grant")
    return difference
