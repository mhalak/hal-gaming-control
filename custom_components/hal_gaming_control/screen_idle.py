"""Strict per-PC Windows console display event evidence for experimental #92.

Windows console OFF is not proof of all physical screens being off. State may
suppress *new* foreground charging when explicitly enabled, but never grants
a bonus by itself. Old agents (display_context v1) cannot authorize anything.
"""
import json
import math
import re
from .foreground_snapshot import _unique_object

FIELDS = frozenset((
    "version", "device_id", "observed_at", "display_state",
    "display_event_age_ms", "display_epoch", "display_sequence",
    "display_scope", "ac_timeout_seconds", "dc_timeout_seconds",
    "power_source", "last_input_idle_ms",
))
MAX_PACKET = 2048
MAX_AGE = 8.0
MAX_FUTURE = 2.0
MAX_EVENT_AGE_MS = 86400000
STATE_TTL = 36.0
EPOCH = re.compile(r"[0-9a-f]{32}")


def _number(value):
    return type(value) in (float, int) and math.isfinite(value)


def decode_display_context(payload, device_id, *, retained, wall_now):
    """Require exact v2 schema, non-retained, fresh source/clock and sane types."""
    if (retained is not False or not isinstance(payload, (str, bytes))
            or not 0 < len(payload) <= MAX_PACKET):
        raise ValueError("Missing fresh display context")
    try:
        row = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, TypeError, RecursionError) as err:
        raise ValueError("Invalid display JSON") from err
    if (not isinstance(row, dict) or row.keys() != FIELDS
            or type(row["version"]) is not int or row["version"] != 2
            or row["device_id"] != device_id
            or row["display_scope"] != "windows_console"
            or not _number(row["observed_at"]) or row["observed_at"] < 0
            or not _number(wall_now)
            or not -MAX_FUTURE <= wall_now - row["observed_at"] < MAX_AGE):
        raise ValueError("Invalid display identity or timestamp")
    for name in ("ac_timeout_seconds", "dc_timeout_seconds"):
        val = row[name]
        if val is not None and (type(val) is not int or not 0 <= val <= 0xffffffff):
            raise ValueError("Invalid display timeout")
    if row["power_source"] not in ("ac", "battery", "unknown"):
        raise ValueError("Invalid power source")
    idle = row["last_input_idle_ms"]
    if idle is not None and (type(idle) is not int or not 0 <= idle <= 86400000):
        raise ValueError("Invalid session idle age")
    state, age, epoch, sequence = (
        row["display_state"], row["display_event_age_ms"],
        row["display_epoch"], row["display_sequence"])
    if state == "unknown":
        if any(value is not None for value in (age, epoch, sequence)):
            raise ValueError("Unknown state must not claim evidence")
    elif (state not in ("on", "dim", "off")
          or type(age) is not int or not 0 <= age <= MAX_EVENT_AGE_MS
          or type(epoch) is not str or EPOCH.fullmatch(epoch) is None
          or type(sequence) is not int or not 1 <= sequence <= (1 << 63) - 1):
        raise ValueError("Invalid display notification receipt")
    return row


class DisplayGate:
    """Volatile ordered display evidence; no inferred state after reconnect."""

    def __init__(self, device_id):
        self.device_id = device_id
        self._watermark = 0.0
        self._epoch = None
        self._sequence = 0
        self.invalidate()

    def invalidate(self):
        self.state = "unknown"
        self._received = None
        self._armed_epoch = None

    def current(self, monotonic_now):
        if (self._received is None or not _number(monotonic_now)
                or not 0 <= monotonic_now - self._received < STATE_TTL):
            self.invalidate()
        return self.state

    def observe(self, payload, *, retained, wall_now, monotonic_now):
        """Return (accepted, new_off_event_or_None), discarding stale replays."""
        try:
            row = decode_display_context(payload, self.device_id,
                                         retained=retained, wall_now=wall_now)
        except (ValueError, TypeError):
            self.invalidate()
            return False, None
        if not _number(monotonic_now):
            self.invalidate()
            return False, None
        if row["observed_at"] <= self._watermark:
            return False, None
        self._watermark = row["observed_at"]
        epoch, sequence, state = (
            row["display_epoch"], row["display_sequence"], row["display_state"])
        if epoch is not None:
            if epoch == self._epoch and sequence < self._sequence:
                self.invalidate()
                return False, None
            if epoch != self._epoch:
                self._armed_epoch = None
            is_new = epoch != self._epoch or sequence > self._sequence
            self._epoch, self._sequence = epoch, sequence
        else:
            is_new = False
        previous = self.current(monotonic_now)
        self.state = state
        self._received = monotonic_now
        if state == "on":
            self._armed_epoch = epoch
        event = None
        if (state == "off" and is_new and self._armed_epoch == epoch
                and previous in ("on", "dim")
                and row["display_event_age_ms"] <= 5000):
            event = row
        if state == "unknown":
            self._armed_epoch = None
        return True, event
