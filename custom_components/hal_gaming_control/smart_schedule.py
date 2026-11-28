"""Read-only schedule projection and absolute, temporary extension planning."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from math import floor, isfinite

from .const import DEFAULTS
from .rule_engine import _schedule_for_date, inside_weekly_schedule

UTC = timezone.utc


def _utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Schedule requires an aware datetime")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ScheduleExtension:
    start: datetime
    end: datetime

    def __post_init__(self):
        object.__setattr__(self, "start", _utc(self.start))
        object.__setattr__(self, "end", _utc(self.end))
        if self.end <= self.start:
            raise ValueError("Schedule extension must have positive duration")


@dataclass(frozen=True)
class ScheduleSnapshot:
    remaining_seconds: float | None
    deadline: datetime | None = None
    extension: ScheduleExtension | None = None


def _transition(left, right, zone):
    """Find the offset discontinuity between two interpretations of a wall time."""
    lo, hi = floor(left.timestamp()), floor(right.timestamp())
    offset = left.astimezone(zone).utcoffset()
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if datetime.fromtimestamp(mid, UTC).astimezone(zone).utcoffset() == offset:
            lo = mid
        else:
            hi = mid
    return datetime.fromtimestamp(hi, UTC)


def _boundary_instants(wall, zone):
    first = wall.replace(tzinfo=zone, fold=0).astimezone(UTC)
    second = wall.replace(tzinfo=zone, fold=1).astimezone(UTC)
    if first == second:
        return {first}
    left, right = sorted((first, second))
    return {left, right, _transition(left, right, zone)}


def _day_boundaries(day, zone, options):
    start, end = _schedule_for_date(options, day)
    _, previous_end = _schedule_for_date(options, day - timedelta(days=1))
    return {instant for clock in (time.min, start, end, previous_end)
            for instant in _boundary_instants(datetime.combine(day, clock), zone)}


def _base_deadline(now, options):
    """Next closure of an open recurring window; None means continuously open."""
    current = _utc(now)
    candidates = set()
    # One complete recurring week plus a boundary day for overnight spillover.
    for offset in range(9):
        candidates.update(_day_boundaries(now.date() + timedelta(days=offset),
                                          now.tzinfo, options))
    return next((point for point in sorted(candidates) if point > current
                 and not inside_weekly_schedule(point.astimezone(now.tzinfo), options)), None)


def schedule_snapshot(options, now, extension=None):
    """Project the continuous open window using the existing local-clock policy."""
    current = _utc(now)
    settings = DEFAULTS | options
    if not settings["enabled"] or settings["unlimited"] or not settings["schedule_enabled"]:
        return ScheduleSnapshot(None)
    base_open = inside_weekly_schedule(now, settings)
    base_end = _base_deadline(now, settings) if base_open else current
    if base_end is None:
        return ScheduleSnapshot(None)
    if extension is not None and extension.start <= base_end and extension.end > current:
        end = max(base_end, extension.end)
        local_end = end.astimezone(now.tzinfo)
        if inside_weekly_schedule(local_end, settings):
            end = _base_deadline(local_end, settings)
        if end is None:
            return ScheduleSnapshot(None)
        return ScheduleSnapshot((end - current).total_seconds(), end, extension)
    return ScheduleSnapshot((base_end - current).total_seconds(), base_end if base_open else None)


def extend_schedule(snapshot, now, seconds):
    """Plan a deadline extension, reopening from now when the window is closed.

    Caller owns authorization and persistence; no recurring settings are changed.
    """
    current = _utc(now)
    if type(seconds) not in (int, float) or not isfinite(seconds) or seconds <= 0:
        raise ValueError("Schedule extension must have positive finite seconds")
    if snapshot.remaining_seconds is None:
        raise ValueError("No finite schedule limit to extend")
    anchor = snapshot.deadline or current
    start = snapshot.extension.start if snapshot.extension else anchor
    return ScheduleExtension(start, anchor + timedelta(seconds=seconds))
