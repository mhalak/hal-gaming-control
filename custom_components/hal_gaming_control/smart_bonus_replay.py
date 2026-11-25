"""Recompute surviving smart grants against their original policy and usage inputs."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from .smart_budget import BonusPlan, Seconds, plan_bonus, select_budget
from .smart_schedule import ScheduleExtension, schedule_snapshot


@dataclass(frozen=True)
class GrantIntent:
    grant_id: str
    at: datetime
    bonus_seconds: int
    # Signed quota balances with ALL smart adjustments excluded; absent = inactive.
    base_balances: Mapping[str, Seconds | None]
    schedule_options: Mapping | None = None


@dataclass(frozen=True)
class AppliedGrant:
    plan: BonusPlan
    schedule: ScheduleExtension | None = None


def _instant(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Grant requires an aware timestamp")
    return value.astimezone(timezone.utc)


def _monday(day):
    return day - timedelta(days=day.weekday())


def project_schedule(options, now, intervals):
    """Include only intervals reachable from the current continuous window."""
    current = _instant(now)
    state = schedule_snapshot(options, now)
    for interval in sorted(intervals, key=lambda item: item.start):
        if state.remaining_seconds is None:
            break
        anchor = state.deadline or current
        if interval.end <= anchor:
            continue
        if interval.start > anchor:
            break
        start = state.extension.start if state.extension else interval.start
        state = schedule_snapshot(options, now, ScheduleExtension(start, interval.end))
    return state


def _validate_order(grants, cancelled_ids):
    ids = [grant.grant_id for grant in grants]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("Grant IDs must be unique and nonempty")
    if set(cancelled_ids) - set(ids):
        raise ValueError("Unknown cancelled grant")
    instants = [_instant(grant.at) for grant in grants]
    if instants != sorted(instants):
        raise ValueError("Grants must be in original chronological order")


def replay_grants(grants, *, cancelled_ids=()):
    """Replay in original journal order; never rewrite measured usage or grant intent.

    Only historical input snapshots supplied by the caller are used. Cancellation
    removes an intent, not merely its old adjustment. This is a pure projection;
    callers own authorization, durable storage and any live policy cutover.
    """
    grants = tuple(grants)
    cancelled_ids = frozenset(cancelled_ids)
    _validate_order(grants, cancelled_ids)
    daily, weekly, intervals, result = {}, {}, [], {}
    for grant in grants:
        if grant.grant_id in cancelled_ids:
            continue
        day = grant.at.date()
        week = _monday(day)
        balances = dict(grant.base_balances)
        if set(balances) - {"daily", "weekly"}:
            raise ValueError("Only quota balances belong in grant input")
        # Validate the original balances before addition (bool is not a quota).
        if select_budget(balances).status == "unknown":
            raise ValueError("Unknown base quota balance")
        for key, carry in (("daily", daily.get(day, 0)), ("weekly", weekly.get(week, 0))):
            if key in balances:
                balances[key] += carry
        state = None
        if grant.schedule_options is not None:
            state = project_schedule(grant.schedule_options, grant.at, intervals)
            if state.remaining_seconds is not None:
                balances["schedule"] = state.remaining_seconds
        plan = plan_bonus(select_budget(balances), grant.bonus_seconds)
        daily[day] = daily.get(day, 0) + plan.extensions.get("daily", 0)
        weekly[week] = weekly.get(week, 0) + plan.extensions.get("weekly", 0)
        interval = None
        if "schedule" in plan.extensions:
            anchor = state.deadline or _instant(grant.at)
            interval = ScheduleExtension(anchor, anchor + timedelta(seconds=plan.extensions["schedule"]))
            intervals.append(interval)
        result[grant.grant_id] = AppliedGrant(plan, interval)
    return result
