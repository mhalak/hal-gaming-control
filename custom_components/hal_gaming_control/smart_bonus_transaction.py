"""Atomic journal candidates for Smart Parent Bonus; no live callers yet."""
from copy import deepcopy

from .parent_bonus import JOURNAL_KEY, _journal, _write, add_parent_grant, revoke_parent_grant
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
    return GrantIntent(row["id"], snapshot.at, row["minutes"] * 60,
                       snapshot.base_balances, snapshot.schedule_options)


def _recompute(journal, device_id, *, new_id=None):
    rows = _smart_rows(journal, device_id)
    intents = [_intent(row, new_id) for row in rows]
    cancelled = {row["id"] for row in rows if row["status"] == "cancelled"}
    applied = replay_grants(intents, cancelled_ids=cancelled)
    for row, intent in zip(rows, intents):
        if row["id"] in cancelled:
            continue
        result = applied[row["id"]]
        record = make_adjustments(intent.at, result.plan.extensions,
                                  schedule_anchor=result.schedule.start if result.schedule else None)
        row["smart_adjustments"] = record
        if row["id"] == new_id:
            row["smart_original_adjustments"] = deepcopy(record)


def prepare_grant(options, device_id, now, amount_minutes, base_balances,
                  schedule_options=None):
    """Build one new grant with its original intent and replayed adjustments.

    Base balances must exclude every smart grant, but include verified usage
    and other applicable policy. Caller authorizes the grant and commits the
    complete returned options in one synchronous HA write.
    """
    snapshot = capture_intent(now, base_balances, schedule_options)
    candidate = add_parent_grant(options, device_id, now, amount_minutes)
    journal = candidate[JOURNAL_KEY]
    event = journal["events"][-1]
    event["smart_intent"] = snapshot
    _recompute(journal, device_id, new_id=event["id"])
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
    _recompute(journal, device_id)
    return _write(candidate, journal, now)
