"""Validate ephemeral, device-scoped foreground candidates for HA Options Flow.

A candidate is only an advisory hint. It never authorizes rule enrollment.
Application edits are HA-only. Revalidate current live observation before saving.
"""
import json
import math
import re

MAX_CANDIDATE_BYTES = 1024
MAX_CANDIDATE_AGE = 8
FUTURE_SKEW = 2
_ALLOWED_FIELDS = {"version", "device_id", "process", "signature", "token", "observed_at"}


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


_JAVA_CLASS = re.compile(r"[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)+", re.ASCII)
_JAVA_JAR = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.+-]{0,95}\.jar", re.IGNORECASE | re.ASCII)
_JAVA_MODULE = re.compile(r"[a-zA-Z_][a-zA-Z_0-9.]*(?:/[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)*)?", re.ASCII)


def _valid_signature(process, signature):
    if signature is None:
        return True
    if (process.casefold() not in ("java.exe", "javaw.exe")
            or not isinstance(signature, dict)
            or set(signature) != {"kind", "value"}):
        return False
    kind, value = signature["kind"], signature["value"]
    if not isinstance(kind, str) or not isinstance(value, str) or len(value) > 128:
        return False
    return bool({
        "java_class": _JAVA_CLASS,
        "java_jar": _JAVA_JAR,
        "java_module": _JAVA_MODULE,
    }.get(kind, re.compile(r"(?!)")).fullmatch(value))


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
    signature = data["signature"]
    if not _valid_signature(process, signature):
        raise ValueError("Unsafe Java launch signature")
    token = data["token"]
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid candidate token")
    observed = data["observed_at"]
    if not _valid_observation(observed, now):
        raise ValueError("Stale or invalid foreground sample")
    return {"process": process, "signature": signature, "token": token, "observed_at": observed}
