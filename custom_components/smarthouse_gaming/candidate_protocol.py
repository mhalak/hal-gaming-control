"""Validate ephemeral, device-scoped foreground candidates for HA Options Flow.

A candidate is only an advisory hint. It never authorizes rule enrollment.
The Windows agent must independently re-check focus and acknowledge any edit.
"""
import json
import math
import re

MAX_CANDIDATE_BYTES = 1024
MAX_CANDIDATE_AGE = 8
FUTURE_SKEW = 2
_ALLOWED_FIELDS = {"version", "device_id", "process", "token", "observed_at"}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate candidate field")
        value[key] = item
    return value


def parse_candidate(topic, payload, device_id, *, retained, now):
    """Return safe process and opaque token or reject stale/foreign messages."""
    if (retained is not False or type(device_id) is not str
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id)
            or topic != f"SmartHouse/Gaming/{device_id}/state/foreground_candidate"
            or not isinstance(payload, (bytes, str))
            or len(payload) > MAX_CANDIDATE_BYTES):
        raise ValueError("Invalid candidate transport")
    try:
        data = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Invalid candidate JSON") from exc
    if (not isinstance(data, dict) or set(data) != _ALLOWED_FIELDS
            or type(data["version"]) is not int or data["version"] != 1
            or data["device_id"] != device_id):
        raise ValueError("Invalid candidate identity")
    process = data["process"]
    if (not isinstance(process, str) or len(process) > 128
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.'()+-]*\.exe", process, re.IGNORECASE)):
        raise ValueError("Unsafe candidate executable")
    token = data["token"]
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid candidate token")
    observed = data["observed_at"]
    if (type(observed) not in (int, float) or not math.isfinite(observed)
            or type(now) not in (int, float) or not math.isfinite(now)
            or not -FUTURE_SKEW <= now - observed < MAX_CANDIDATE_AGE):
        raise ValueError("Stale or invalid foreground sample")
    return {"process": process, "token": token, "observed_at": observed}
