"""Shared exact-second effective budget projection; no new grant callers."""
from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from .const import DEFAULTS
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


def effective_snapshot(options, totals, now, device_id, *, ready):
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
    return EffectiveSnapshot(selection, base_balances, effective, schedule)
