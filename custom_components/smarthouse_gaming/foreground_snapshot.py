"""Validate atomic foreground samples independently of transport and accounting."""
import json
import math
import re

MAX_SAMPLE_AGE = 10.0
MAX_FUTURE_SKEW = 2.0
MAX_PAYLOAD = 4096
MAX_SEQUENCE = (1 << 63) - 1
_FIELDS = frozenset(("version", "device_id", "epoch", "sequence",
                     "observed_at", "active_game", "gaming_active"))
_RESERVED = frozenset(("", "idle", "unknown", "unavailable"))


def _finite(value):
    return type(value) in (int, float) and abs(value) <= 253402300799 and math.isfinite(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate snapshot field")
        result[key] = value
    return result


def _decode(payload, device_id):
    if not isinstance(payload, (str, bytes)) or len(payload) > MAX_PAYLOAD:
        raise ValueError("Invalid snapshot size")
    data = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or data.keys() != _FIELDS:
        raise ValueError("Invalid snapshot fields")
    if type(data["version"]) is not int or data["version"] != 1 or data["device_id"] != device_id:
        raise ValueError("Invalid snapshot identity")
    epoch, sequence = data["epoch"], data["sequence"]
    if not isinstance(epoch, str) or not re.fullmatch(r"[0-9a-f]{32}", epoch):
        raise ValueError("Invalid snapshot epoch")
    if type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE:
        raise ValueError("Invalid snapshot sequence")
    if not _finite(data["observed_at"]) or data["observed_at"] < 0:
        raise ValueError("Invalid observation timestamp")
    return data


def _state(data, enrolled):
    game, flag = data["active_game"], data["gaming_active"]
    if not isinstance(game, str) or not isinstance(flag, str):
        raise ValueError("Invalid foreground state")
    if (game, flag) == ("idle", "OFF"):
        return "idle"
    if (game, flag) == ("unknown", "UNKNOWN"):
        return None
    if flag == "ON" and game in enrolled and game not in _RESERVED and " | " not in game:
        return game
    raise ValueError("Inconsistent foreground state")


class ForegroundLiveness:
    """A per-device gate; None always means unconfirmed, never confirmed idle.

    Watermarks survive transport invalidation but not HA process recreation.
    Requires device-scoped trusted MQTT, non-retained periodic snapshots and
    synchronized clocks. It does not authenticate publishers or write history.
    """

    def __init__(self, device_id, enrolled):
        self.device_id = device_id
        self.enrolled = frozenset(enrolled)
        self._epoch = None
        self._sequence = 0
        self._observed = None
        self._retired = {}
        self.invalidate()

    def invalidate(self):
        """Discard current evidence without resetting the replay watermark."""
        self._value = None
        self._received = None
        self._expires = None

    def current(self, monotonic_now):
        if (self._expires is not None and _finite(monotonic_now)
                and self._received <= monotonic_now < self._expires):
            return self._value
        self.invalidate()
        return None

    def _ordered(self, data, monotonic_now):
        # Remember retired epochs through the maximum possible valid packet age.
        # The global timestamp watermark additionally spans all older epochs.
        self._retired = {epoch: deadline for epoch, deadline in self._retired.items()
                         if deadline > monotonic_now}
        epoch, sequence = data["epoch"], data["sequence"]
        observed = data["observed_at"]
        if epoch in self._retired:
            return False
        if self._observed is None:
            return True
        if epoch == self._epoch:
            return sequence > self._sequence and observed >= self._observed
        return observed > self._observed

    def _accept(self, data, value, age, monotonic_now):
        epoch = data["epoch"]
        if self._epoch is not None and epoch != self._epoch:
            self._retired[self._epoch] = monotonic_now + MAX_SAMPLE_AGE + MAX_FUTURE_SKEW
        self._epoch, self._sequence = epoch, data["sequence"]
        self._observed = data["observed_at"]
        self._received = monotonic_now
        self._expires = monotonic_now + MAX_SAMPLE_AGE - max(0, age)
        self._value = value

    def observe(self, payload, *, retained, wall_now, monotonic_now):
        """Accept only fresh, coherent, strictly ordered live observations."""
        if retained is not False:
            return False
        if not _finite(wall_now) or not _finite(monotonic_now):
            self.invalidate()
            return False
        if self._received is not None and monotonic_now < self._received:
            self.invalidate()
            return False
        try:
            data = _decode(payload, self.device_id)
            value = _state(data, self.enrolled)
        except (ValueError, TypeError, RecursionError):
            self.invalidate()
            return False
        age = wall_now - data["observed_at"]
        if not -MAX_FUTURE_SKEW <= age < MAX_SAMPLE_AGE:
            self.invalidate()
            return False
        if not self._ordered(data, monotonic_now):
            return False
        self._accept(data, value, age, monotonic_now)
        return True
