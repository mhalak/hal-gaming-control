"""Shared exact-second effective budget projection; no new grant callers."""
from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from .const import DEFAULTS
from .gaming_penalty import project_penalties
from .parent_bonus import parent_smart_grants
from .rule_engine import effective_budget_limit
from .smart_budget import BudgetSelection, Seconds, select_budget
from .smart_bonus_replay import project_schedule
from .smart_schedule import ScheduleExtension, ScheduleSnapshot


@dataclass(frozen=True)
class EffectiveSnapshot:
    selection: BudgetSelection
    base_balances: Mapping[str, Seconds | None]
    limits_seconds: Mapping[str, Seconds]
    schedule: ScheduleSnapshot


def _verified(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def quota_limits(options, now, adjustments):
    """Base quota seconds, and effective seconds after smart adjustments."""
    base = {}
    for period in ("daily", "weekly"):
        limit = effective_budget_limit(options, now, period)
        if limit >= 0:
            base[period] = limit * 60
    effective = dict(base)
    for period in effective:
        effective[period] += sum(getattr(row, period + "_seconds") for row in adjustments.values())
    return base, effective


def effective_snapshot(options, totals, now, device_id, *, ready, include_penalties=True):
    """One policy snapshot for restriction, future receipt, and warning actions."""
    settings = DEFAULTS | options
    adjustments = parent_smart_grants(settings, device_id, now)
    base, effective = quota_limits(settings, now, adjustments)
    intervals = [ScheduleExtension(row.schedule_start, row.schedule_end)
                 for row in adjustments.values() if row.schedule_end is not None]
    schedule = project_schedule(settings, now, intervals)
    base_balances = {period: limit - totals[period]
                     if ready and _verified(totals.get(period)) else None
                     for period, limit in base.items()}
    balances = {period: value + effective[period] - base[period]
                if value is not None else None
                for period, value in base_balances.items()}
    if schedule.remaining_seconds is not None:
        balances["schedule"] = schedule.remaining_seconds if ready else None
    selection = select_budget(balances, enabled=settings["enabled"],
                              unlimited=settings["unlimited"])
    if settings["gaming_suspended"]:
        # An explicit parent suspension outranks every ordinary policy/override.
        selection = (BudgetSelection("limited", {"suspended": 0}, 0, ("suspended",))
                     if ready else BudgetSelection("unknown", {"suspended": None}))
    elif include_penalties:
        selection = project_penalties(selection, settings, device_id, now, ready=ready)
    return EffectiveSnapshot(selection, base_balances, effective, schedule)


def effective_summary(snapshot, totals):
    """Display and popup fields derived from the same unrounded snapshot."""
    selection = snapshot.selection
    remaining = selection.remaining_seconds
    source = selection.limiting_sources[0] if selection.limiting_sources else None
    used = totals.get("weekly" if source == "weekly" else "daily") if source else None
    used = used if _verified(used) else None
    total = used + remaining if used is not None and remaining is not None else None
    percent = (100 * remaining / total if total else 0) if total is not None else None
    return {
        "budget_status": selection.status,
        "limiting_budget": source,
        "limiting_sources": list(selection.limiting_sources),
        "remaining_seconds": remaining,
        "remaining_minutes": remaining / 60 if remaining is not None else None,
        "effective_budget_minutes": total / 60 if total is not None else None,
        "used_minutes": used / 60 if used is not None else None,
        "remaining_percent": percent,
        "schedule_end": snapshot.schedule.deadline.isoformat() if snapshot.schedule.deadline else None,
    }
