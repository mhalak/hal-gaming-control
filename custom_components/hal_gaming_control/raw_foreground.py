"""HA-owned raw foreground identity decoding and stable-key accounting.

This pure core is not yet wired into the running coordinator/Recorder. Windows
game labels are never consulted. The caller must persist confirmed segments
and establish an explicit cutover before replacing production budget sources.
"""
import json
import re

from .app_registry import identity_key, load_apps
from .candidate_protocol import _valid_process, _valid_signature
from .foreground_accounting import ForegroundLedger
from .foreground_snapshot import (
    MAX_PAYLOAD, MAX_SEQUENCE, _finite, _unique_object,
)

_RAW_FIELDS = frozenset((
    "version", "device_id", "epoch", "sequence", "observed_at",
    "state", "process", "signature",
))
_EPOCH = re.compile(r"[0-9a-f]{32}")



def _valid_raw_stamp(value):
    """Bound epoch, strictly positive sequence and finite wall timestamp."""
    return (isinstance(value["epoch"], str)
            and _EPOCH.fullmatch(value["epoch"]) is not None
            and type(value["sequence"]) is int
            and 1 <= value["sequence"] <= MAX_SEQUENCE
            and _finite(value["observed_at"])
            and value["observed_at"] >= 0)

def decode_raw_identity(payload, device_id):
    """Fail closed on malformed, foreign or ambiguous raw MQTT data."""
    if not isinstance(payload, (bytes, str)) or len(payload) > MAX_PAYLOAD:
        raise ValueError("Invalid raw foreground packet size")
    try:
        value = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid raw foreground JSON") from exc
    if not isinstance(value, dict) or value.keys() != _RAW_FIELDS:
        raise ValueError("Invalid raw foreground fields")
    if type(value["version"]) is not int or value["version"] != 2:
        raise ValueError("Unsupported foreground protocol")
    if not isinstance(device_id, str) or value["device_id"] != device_id:
        raise ValueError("Wrong foreground device")
    if not _valid_raw_stamp(value):
        raise ValueError("Invalid foreground sequence or timestamp")
    state, process, signature = (value["state"], value["process"], value["signature"])
    if state == "foreground":
        if not _valid_process(process) or not _valid_signature(process, signature):
            raise ValueError("Unsafe foreground executable identity")
    elif state in ("idle", "unknown"):
        if process is not None or signature is not None:
            raise ValueError("Idle/unknown must not carry a process")
    else:
        raise ValueError("Invalid foreground state")
    return value


def _effective_game(packet, apps):
    if packet["state"] == "idle":
        return "idle", "OFF"
    if packet["state"] == "unknown":
        return "unknown", "UNKNOWN"
    try:
        raw_key = identity_key(packet["process"], packet["signature"])
    except ValueError:
        # Bare Java cannot identify a particular app: no guessing or charging.
        return "unknown", "UNKNOWN"
    if raw_key not in apps:
        return "idle", "OFF"
    return raw_key, "ON"


class HAOwnedForeground:
    """Map raw observations to stable HA keys; expose only configured names.

    Segments use composite executable+signature keys, not aliases, so renaming
    a tracked application does not rewrite or reset its history.
    """

    def __init__(self, device_id, tracked_apps, *, intervals=()):
        self.device_id = device_id
        self.apps = load_apps(tracked_apps)
        # Historic keys remain countable after an explicit HA Rename/Remove.
        # Only self.apps can match NEW live samples: removed apps stay untracked.
        history = tuple(intervals)
        archive = {row[2] for row in history
                   if isinstance(row, (tuple, list)) and len(row) == 3}
        self.ledger = ForegroundLedger(
            device_id, set(self.apps) | archive, intervals=history)

    def invalidate(self):
        self.ledger.invalidate()

    def observe(self, payload, *, retained, wall_now, monotonic_now):
        try:
            packet = decode_raw_identity(payload, self.device_id)
            key, active = _effective_game(packet, self.apps)
        except (ValueError, TypeError, RecursionError):
            self.invalidate()
            return False
        legacy_shape = json.dumps({
            "version": 1,
            "device_id": self.device_id,
            "epoch": packet["epoch"],
            "sequence": packet["sequence"],
            "observed_at": packet["observed_at"],
            "active_game": key,
            "gaming_active": active,
        })
        return self.ledger.observe(
            legacy_shape, retained=retained,
            wall_now=wall_now, monotonic_now=monotonic_now)

    def current(self, monotonic_now):
        key = self.ledger.current(monotonic_now)
        if key in (None, "idle"):
            return key
        return self.apps[key]["name"]

    def totals(self, now):
        return self.ledger.totals(now)

    def export_segments(self):
        return self.ledger.export_segments()
