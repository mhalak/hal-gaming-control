"""Count only bounded intervals confirmed by successive live foreground snapshots.

Each positively charged interval has two independent, fresh, correctly ordered
observations of the SAME tracked foreground application. Transitions, gaps,
offline/unknown samples and legacy process lists are never charged. This pure
ledger does not activate a historical cutover or write to the Recorder.
"""
from datetime import datetime
import math

from .foreground_snapshot import (
    ForegroundLiveness, MAX_SAMPLE_AGE, _decode,
)
from .rule_engine import calculate


def _validated_segments(segments, enrolled):
    result = []
    for row in segments:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise ValueError("Invalid foreground accounting segment")
        start, end, game = row
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start < end or game not in enrolled
                or (result and start < result[-1][1])):
            raise ValueError("Invalid foreground accounting segment")
        if result and result[-1][1] == start and result[-1][2] == game:
            result[-1] = (result[-1][0], end, game)
        else:
            result.append((start, end, game))
    return result


class ForegroundLedger:
    """Volatile accounting state; caller owns durable checkpointing and cutover.

    Loaded segments are history only. Never trust a pre-restart snapshot as a
    live continuation, even when the previous epoch and game match.
    """

    def __init__(self, device_id, enrolled, *, intervals=()):
        self.device_id = device_id
        self.enrolled = frozenset(enrolled)
        self._live = ForegroundLiveness(device_id, self.enrolled)
        self._segments = _validated_segments(intervals, self.enrolled)
        self._previous = None

    def invalidate(self):
        """Disconnect, stale source, invalid packet or service restart."""
        self._live.invalidate()
        self._previous = None

    def current(self, monotonic_now):
        """A tracked game, 'idle' or None for unknown/stale."""
        return self._live.current(monotonic_now)

    def observe(self, payload, *, retained, wall_now, monotonic_now):
        """Accept a live sample, charging only an uninterrupted identical pair."""
        if not self._live.observe(payload, retained=retained, wall_now=wall_now,
                                  monotonic_now=monotonic_now):
            self.invalidate()
            return False
        data = _decode(payload, self.device_id)  # already checked by the gate
        game, observed, epoch = (self._live.current(monotonic_now),
                                 data["observed_at"], data["epoch"])
        prior = self._previous
        if prior and game is not None and game != "idle":
            start, before, previous_epoch = prior
            if (before == game and previous_epoch == epoch
                    and 0 < observed - start <= MAX_SAMPLE_AGE):
                self._charge(start, observed, game)
        self._previous = (observed, game, epoch)
        return True

    def _charge(self, start, end, game):
        if self._segments and self._segments[-1][1] == start and self._segments[-1][2] == game:
            previous = self._segments[-1]
            self._segments[-1] = (previous[0], end, game)
        else:
            self._segments.append((start, end, game))

    def export_segments(self):
        """Immutable export for a separately authenticated durable checkpoint."""
        return tuple(self._segments)

    def totals(self, now: datetime):
        """Calculate by local day/week boundaries, with zero invented intervals."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Accounting time must be timezone-aware")
        transitions = []
        for start, end, game in self._segments:
            transitions.extend(((start, game), (end, "unavailable")))
        return calculate(transitions, now, self.enrolled)
