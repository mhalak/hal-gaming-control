"""Smart budget receipt from verified usage and the shared policy projection."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from .const import DEFAULTS
from .public_holidays import weekend_equivalent
from .unlimited_bonus import credit_seconds
from .parent_bonus import _journal, grant_seconds, parent_bonus_legacy_today
from .rule_engine import effective_budget_limit, windows
from .screen_idle_bonus import screen_idle_events_today


@dataclass(frozen=True)
class ReceiptLine:
    title: str
    seconds: float
    grant_id: str | None = None


@dataclass(frozen=True)
class SmartReceipt:
    source: str
    used: float
    remaining: float
    lines: tuple[ReceiptLine, ...]

    @property
    def total(self):
        return self.used + self.remaining


def _verified(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def _active_rows(options, device_id):
    return [row for row in _journal(options)["events"]
            if row["device_id"] == device_id and row["status"] == "active"]


def _monday(day):
    return (day - timedelta(days=day.weekday())).isoformat()


def _quota_adjustment(row, period, now):
    record = row.get("smart_adjustments")
    if record is None:
        return row["minutes"] * 60 if period == "daily" and row["local_date"] == now.date().isoformat() else 0
    key, value = ("day", now.date().isoformat()) if period == "daily" else ("week", _monday(now.date()))
    return record[period + "_seconds"] if record[key] == value else 0


def _interval(row):
    record = row.get("smart_adjustments") or {}
    start, end = record.get("schedule_start_utc"), record.get("schedule_end_utc")
    return (datetime.fromisoformat(start).timestamp(), datetime.fromisoformat(end).timestamp()) if start else None


def _smart_eligible(row, prior, options, totals, now):
    """Lock a grant after any of its quota or wall-clock adjustment is consumed."""
    if row["local_date"] != now.date().isoformat():
        return False
    record = row.get("smart_adjustments")
    if not record or not record.get("granted_at_utc"):
        return False
    interval = _interval(row)
    if interval and now.timestamp() > interval[0]:
        return False
    for period in ("daily", "weekly"):
        amount = record[period + "_seconds"]
        if not amount:
            continue
        limit = effective_budget_limit(options, now, period)
        used = totals.get(period)
        if limit < 0 or not _verified(used):
            return False
        carry = sum(_quota_adjustment(item, period, now) for item in prior
                    if "smart_adjustments" in item)
        if used - credit_seconds(totals, period) > limit * 60 + carry:
            return False
    return bool(interval or record["daily_seconds"] or record["weekly_seconds"])


def _titles(rows, now):
    clocks = [datetime.fromisoformat(row["created_at_utc"]).astimezone(now.tzinfo).strftime("%H:%M")
              for row in rows]
    counts, seen = Counter(clocks), Counter()
    result = {}
    for row, clock in zip(rows, clocks):
        seen[clock] += 1
        suffix = f" #{seen[clock]}" if counts[clock] > 1 else ""
        kind = "Sync Bonus" if row.get("source") == "sync" else "Parent Bonus"
        result[row["id"]] = f"{kind} ({clock}{suffix})"
    return result


def _parent_line(row, amount, title, eligible):
    seconds = grant_seconds(row)
    if row.get("source") == "sync" and (seconds % 60 or amount != seconds):
        minutes, remainder = divmod(seconds, 60)
        title += f" (+{minutes}m {remainder}s granted)"
    elif amount != seconds:
        title += f" (+{row['minutes']} min granted)"
    return ReceiptLine(title, amount, row["id"] if eligible else None)


def _quota_lines(options, rows, device_id, now, totals, source, titles):
    settings = DEFAULTS | options
    if source == "weekly":
        lines = [ReceiptLine("Weekly Budget", settings["weekly"] * 60)]
    else:
        lines = [ReceiptLine("Daily Budget", settings["daily"] * 60)]
        if weekend_equivalent(settings, now.date()) and settings["weekend_bonus"]:
            lines.append(ReceiptLine("Weekend Bonus", settings["weekend_bonus"] * 60))
        legacy = parent_bonus_legacy_today(settings, now)
        if legacy:
            lines.append(ReceiptLine("Legacy Parent Bonus", legacy * 60))
        for event in screen_idle_events_today(settings, now, device_id):
            clock = datetime.fromtimestamp(event["off_at_utc"], now.tzinfo).strftime("%H:%M")
            lines.append(ReceiptLine(f"Screen Off Bonus ({clock})", event["minutes"] * 60))
    credit = credit_seconds(totals, source)
    if credit:
        lines.append(ReceiptLine("Unlimited Bonus", credit))
    for index, row in enumerate(rows):
        amount = _quota_adjustment(row, source, now)
        if not amount and row["local_date"] != now.date().isoformat():
            continue
        if "smart_adjustments" in row:
            eligible = _smart_eligible(row, rows[:index], settings, totals, now)
        else:
            if source != "daily" or not amount:
                continue
            # Legacy daily-only grant attribution uses the established FIFO rule.
            used = totals.get("daily")
            base = effective_budget_limit(settings, now, "daily") * 60
            prior_legacy = sum(_quota_adjustment(item, "daily", now) for item in rows[:index]
                               if "smart_adjustments" not in item)
            all_legacy = sum(_quota_adjustment(item, "daily", now) for item in rows
                             if "smart_adjustments" not in item)
            eligible = (_verified(used) and used - credit_seconds(totals, "daily")
                        <= base - all_legacy + prior_legacy)
        lines.append(_parent_line(row, amount, titles[row["id"]], eligible))
    return lines


def _union(intervals):
    result = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def _duration(intervals):
    return sum(end - start for start, end in intervals)


def _schedule_lines(options, rows, now, totals, snapshot, segments, titles):
    today = windows(now)["daily"].timestamp()
    current = now.timestamp()
    deadline = snapshot.schedule.deadline.timestamp() if snapshot.schedule.deadline else current
    used, remaining = totals["daily"], snapshot.selection.remaining_seconds
    entries = []
    parents = []
    for index, row in enumerate(rows):
        interval = _interval(row)
        if interval and interval[1] > today:
            start, end = max(today, interval[0]), interval[1]
            entries.append((start, end))
            parents.append(_parent_line(row, end - start, titles[row["id"]],
                           _smart_eligible(row, rows[:index], options, totals, now)))
        elif "smart_adjustments" in row and row["local_date"] == now.date().isoformat():
            parents.append(_parent_line(row, 0, titles[row["id"]],
                           _smart_eligible(row, rows[:index], options, totals, now)))
    elapsed = _union((start, min(end, current)) for start, end in entries)
    future = _union((max(start, current), min(end, deadline)) for start, end in entries)
    played = min(used, sum(max(0, min(end, last) - max(start, first))
                            for start, end in elapsed for first, last, _ in segments))
    regular = max(0, remaining - _duration(future))
    label = "Daily Budget (Schedule Adjusted)" if regular else "Daily Budget"
    credit = credit_seconds(totals, "daily")
    lines = [ReceiptLine(label, used - played - credit)]
    if credit:
        lines.append(ReceiptLine("Unlimited Bonus", credit))
    if regular:
        lines.append(ReceiptLine("Until Schedule Limit", regular))
    lines.extend(parents)
    expired = max(0, _duration(elapsed) - played)
    if expired:
        lines.append(ReceiptLine("Expired Schedule Bonus", -expired))
    return lines


def smart_receipt(options, totals, now, device_id, snapshot, segments):
    """Reconcile selected-source receipt without changing measured accounting.

    Segments are verified ledger intervals; only the schedule receipt needs
    their intersection with granted wall-clock intervals. No estimated play.
    """
    selection = snapshot.selection
    if selection.status != "limited":
        return None
    source = selection.limiting_sources[0]
    used = totals.get("weekly" if source == "weekly" else "daily")
    if not _verified(used):
        return None
    rows = _active_rows(options, device_id)
    titles = _titles(rows, now)
    if source == "schedule":
        if segments is None and any(_interval(row) for row in rows):
            return None
        lines = _schedule_lines(options, rows, now, totals, snapshot, segments or (), titles)
    else:
        lines = _quota_lines(options, rows, device_id, now, totals, source, titles)
    difference = used + selection.remaining_seconds - sum(row.seconds for row in lines)
    if abs(difference) > 0.000001:
        title = "Schedule Adjustment" if source == "schedule" else "Budget Overrun Adjustment"
        lines.append(ReceiptLine(title, difference))
    return SmartReceipt(source, used, selection.remaining_seconds, tuple(lines))
