"""Pure Smart Budget policy arithmetic; no persistence or enforcement side effects."""
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping

SOURCES = ("daily", "weekly", "schedule")
Seconds = int | float


@dataclass(frozen=True)
class BudgetSelection:
    status: str
    balances: Mapping[str, Seconds | None]
    remaining_seconds: Seconds | None = None
    limiting_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class BonusPlan:
    target_seconds: Seconds
    extensions: Mapping[str, Seconds]


def select_budget(balances: Mapping[str, Seconds | None], *,
                  enabled: bool = True, unlimited: bool = False) -> BudgetSelection:
    """Absent = inactive; None/invalid = unknown; signed quota debt is retained.

    The schedule adapter must supply zero for a closed window, not elapsed debt.
    This snapshot is for the current instant, not a forecast across quota resets.
    """
    values = MappingProxyType({key: balances[key] for key in SOURCES if key in balances})
    if not enabled:
        return BudgetSelection("disabled", values)
    if unlimited or not values:
        return BudgetSelection("unlimited", values)
    if any(type(value) not in (int, float) or not isfinite(value)
           for value in values.values()):
        return BudgetSelection("unknown", values)
    available = {key: max(0, value) for key, value in values.items()}
    remaining = min(available.values())
    limiting = tuple(key for key in SOURCES if available.get(key) == remaining)
    return BudgetSelection("limited", values, remaining, limiting)


def plan_bonus(selection: BudgetSelection, bonus_seconds: int) -> BonusPlan:
    """Plan minimum extensions against the signed balances without mutating policy."""
    if type(bonus_seconds) is not int or bonus_seconds <= 0:
        raise ValueError("Bonus must be positive whole seconds")
    if selection.status != "limited" or selection.remaining_seconds is None:
        raise ValueError("A finite, known budget is required")
    target = selection.remaining_seconds + bonus_seconds
    extensions = {key: target - balance for key, balance in selection.balances.items()
                  if balance < target}
    return BonusPlan(target, MappingProxyType(extensions))
