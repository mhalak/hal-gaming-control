"""Atomic journal candidates for Smart Parent Bonus; no live callers yet."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from .parent_bonus import (
    JOURNAL_KEY, RETENTION_DAYS, SYNC_JOURNAL_VERSION, _append_grant, _journal,
    _write, add_parent_grant, grant_seconds, revoke_parent_grant,
)
from .smart_bonus_intent import capture_intent, read_intent
from .smart_bonus_record import active_adjustments, make_adjustments
from .smart_bonus_replay import GrantIntent, replay_grants


def _smart_rows(journal, device_id):
    return [row for row in journal["events"] if row["device_id"] == device_id
            and ("smart_adjustments" in row or "smart_intent" in row)]


def _intent(row, new_id):
    if "smart_intent" not in row:
        raise ValueError("Smart grant has no historical intent")
    snapshot = read_intent(row["smart_intent"])
    if (row["smart_intent"]["at_utc"] != row["created_at_utc"]
            or snapshot.at.date().isoformat() != row["local_date"]):
        raise ValueError("Smart bonus intent does not match grant")
    if row["id"] != new_id:
        original = row.get("smart_original_adjustments")
        if (not isinstance(original, dict)
                or original.get("granted_at_utc") != row["created_at_utc"]
                or original.get("day") != row["local_date"]):
            raise ValueError("Smart bonus original adjustment audit missing or invalid")
        active_adjustments(original, snapshot.at)
    return GrantIntent(row["id"], snapshot.at, grant_seconds(row),
                       snapshot.base_balances, snapshot.schedule_options)


def _recompute(journal, device_id, *, from_id, new_id=None):
    rows = _smart_rows(journal, device_id)
    intents = [_intent(row, new_id) for row in rows]
    instants = [intent.at.timestamp() for intent in intents]
    if instants != sorted(instants):
        raise ValueError("Smart grants out of chronological order")
    index = next(i for i, row in enumerate(rows) if row["id"] == from_id)
    seed = [(intent.at, active_adjustments(row["smart_adjustments"], intent.at))
            for row, intent in zip(rows[:index], intents[:index]) if row["status"] == "active"]
    rows, intents = rows[index:], intents[index:]
    cancelled = {row["id"] for row in rows if row["status"] == "cancelled"}
    applied = replay_grants(intents, cancelled_ids=cancelled, seed=seed)
    for row, intent in zip(rows, intents):
        if row["id"] in cancelled:
            continue
        result = applied[row["id"]]
        record = make_adjustments(intent.at, result.plan.extensions,
                                  schedule_anchor=result.schedule.start if result.schedule else None)
        row["smart_adjustments"] = record
        if row["id"] == new_id:
            row["smart_original_adjustments"] = deepcopy(record)


def _retain(row, cutoff, earliest):
    if row["local_date"] >= cutoff:
        return True
    if row["status"] != "active":
        return False
    end = row.get("smart_adjustments", {}).get("schedule_end_utc")
    return end is not None and datetime.fromisoformat(end) > earliest


def _compact(options, now):
    """Drop only expired old audit records; retained prefixes are frozen."""
    journal = _journal(options)
    cutoff = (now.date() - timedelta(days=RETENTION_DAYS)).isoformat()
    # Keep old intervals that could still affect any cancellable current-day
    # grant, including a grant created before a local clock/zone adjustment.
    current = now.astimezone(timezone.utc)
    earliest = min([current - timedelta(days=2)] + [
        datetime.fromisoformat(row["created_at_utc"])
        for row in journal["events"] if row["local_date"] == now.date().isoformat()
        and "smart_adjustments" in row])
    journal["events"] = [row for row in journal["events"] if _retain(row, cutoff, earliest)]
    return _write(options, journal, now)


def prepare_grant(options, device_id, now, amount_minutes, base_balances,
                  schedule_options=None):
    """Build one new grant with its original intent and replayed adjustments.

    Base balances must exclude every smart grant, but include verified usage
    and other applicable policy. Caller authorizes the grant and commits the
    complete returned options in one synchronous HA write.
    """
    snapshot = capture_intent(now, base_balances, schedule_options)
    candidate = add_parent_grant(_compact(options, now), device_id, now, amount_minutes)
    journal = candidate[JOURNAL_KEY]
    event = journal["events"][-1]
    event["smart_intent"] = snapshot
    _recompute(journal, device_id, from_id=event["id"], new_id=event["id"])
    return _write(candidate, journal, now)


def prepare_sync_grant(options, device_id, now, amount_seconds, base_balances,
                       schedule_options=None):
    """Persist one exact-second sync grant, using the same replay as manual grants."""
    if type(amount_seconds) is not int or not 0 < amount_seconds <= 36000:
        raise ValueError("Sync bonus must be 1–36000 whole seconds")
    snapshot = capture_intent(now, base_balances, schedule_options)
    candidate = _compact(options, now)
    journal = _append_grant(candidate, device_id, now, {
        "minutes": amount_seconds // 60, "amount_seconds": amount_seconds,
        "source": "sync", "smart_intent": snapshot,
    })
    journal["version"] = SYNC_JOURNAL_VERSION
    event = journal["events"][-1]
    _recompute(journal, device_id, from_id=event["id"], new_id=event["id"])
    return _write(candidate, journal, now)


def cancel_grant(options, device_id, grant_id, now):
    """Prepare cancellation plus dependent replay, without mutating inputs.

    Preserve existing same-day eligibility. Consumed-grant/UI authorization
    must be enforced by the eventual caller before this pure mutation.
    """
    journal = _journal(options)
    target = next((row for row in _smart_rows(journal, device_id)
                   if row["id"] == grant_id), None)
    if target is None:
        raise ValueError("Unknown smart grant for this device")
    intent = _intent(target, None)
    if now.tzinfo is None or now.utcoffset() is None or now.timestamp() < intent.at.timestamp():
        raise ValueError("Cancellation precedes smart grant")
    candidate = revoke_parent_grant(options, device_id, grant_id, now)
    journal = candidate[JOURNAL_KEY]
    _recompute(journal, device_id, from_id=grant_id)
    return _write(candidate, journal, now)
