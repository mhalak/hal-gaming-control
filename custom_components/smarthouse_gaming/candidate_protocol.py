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


def _valid_transport(topic, payload, device_id, retained):
    return (retained is False and type(device_id) is str
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id)
            and topic == f"SmartHouse/Gaming/{device_id}/state/foreground_candidate"
            and isinstance(payload, (bytes, str))
            and len(payload) <= MAX_CANDIDATE_BYTES)


def _valid_process(process):
    return (isinstance(process, str) and len(process) <= 128
            and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.'()+-]*\.exe",
                                  process, re.IGNORECASE)))


def _valid_observation(observed, now):
    return (type(observed) in (int, float) and math.isfinite(observed)
            and type(now) in (int, float) and math.isfinite(now)
            and -FUTURE_SKEW <= now - observed < MAX_CANDIDATE_AGE)


def parse_candidate(topic, payload, device_id, *, retained, now):
    """Return safe process and opaque token or reject stale/foreign messages."""
    if not _valid_transport(topic, payload, device_id, retained):
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
    if not _valid_process(process):
        raise ValueError("Unsafe candidate executable")
    token = data["token"]
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid candidate token")
    observed = data["observed_at"]
    if not _valid_observation(observed, now):
        raise ValueError("Stale or invalid foreground sample")
    return {"process": process, "token": token, "observed_at": observed}
