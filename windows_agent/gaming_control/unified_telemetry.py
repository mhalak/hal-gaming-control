"""Issue #176: strictly bounded read-only Windows telemetry v3 snapshot.

Only sanitized, freshly validated evidence enters these helpers. A failed
interactive sample is UNKNOWN, never fabricated IDLE. No policy or commands.
"""
import json
import math
import re

VERSION = 3
MAX_BYTES = 4096
MAX_SAMPLE_AGE_S = 1.5
MAX_EVENT_AGE_MS = 86400000
MAX_UPTIME_SECONDS = (1 << 63) - 1
MAX_SEQUENCE = (1 << 63) - 1
PERIOD_S = 2.0
EXPIRY_S = 6
HEX32 = re.compile(r"[0-9a-f]{32}")
SHA40 = re.compile(r"[0-9a-f]{40}")
DEVICE = re.compile(r"[A-Za-z0-9_-]{1,64}")
SEMVER = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def sample_age_ms(monotonic_sample, monotonic_now):
    """Time since an authenticated helper sample, or None on any ambiguity."""
    if (not finite(monotonic_sample) or not finite(monotonic_now)
            or not 0 <= monotonic_now - monotonic_sample <= MAX_SAMPLE_AGE_S):
        return None
    return int((monotonic_now - monotonic_sample) * 1000)


def foreground_fields(state, parts, sample_age):
    """Return one of foreground / confirmed idle / unknown with nullability."""
    if sample_age is None:
        return {"state": "unknown", "process": None,
                "signature": None, "sample_age_ms": None}
    if state == "idle" and parts == (None, None):
        return {"state": "idle", "process": None,
                "signature": None, "sample_age_ms": sample_age}
    if state == "foreground" and isinstance(parts, tuple) and len(parts) == 2:
        process, signature = parts
        if isinstance(process, str) and process and len(process) <= 128:
            return {"state": "foreground", "process": process,
                    "signature": signature, "sample_age_ms": sample_age}
    return {"state": "unknown", "process": None,
            "signature": None, "sample_age_ms": None}


def _policy(policy, idle_ms, age_ms):
    """Power-plan settings are read-only; invalid values never leak."""
    empty = (None, None, "unknown", None)
    if not isinstance(policy, dict):
        return empty
    ac, dc, source = (policy.get("ac_timeout_seconds"),
                      policy.get("dc_timeout_seconds"),
                      policy.get("power_source"))
    for timeout in (ac, dc):
        if timeout is not None and (type(timeout) is not int
                                    or not 0 <= timeout <= 0xffffffff):
            return empty
    if source not in ("ac", "battery", "unknown"):
        return empty
    if (age_ms is None or type(idle_ms) is not int
            or not 0 <= idle_ms + age_ms <= MAX_EVENT_AGE_MS):
        idle_ms = None
    else:
        idle_ms += age_ms
    return ac, dc, source, idle_ms


def _event(state, event_age_ms, epoch, sequence, sample_age):
    """Recompute event age at envelope capture, without manufacturing an edge."""
    if (state not in ("on", "dim", "off") or sample_age is None
            or type(event_age_ms) is not int
            or not 0 <= event_age_ms + sample_age <= MAX_EVENT_AGE_MS
            or type(epoch) is not str or HEX32.fullmatch(epoch) is None
            or type(sequence) is not int
            or not 1 <= sequence <= MAX_SEQUENCE):
        return "unknown", None, None, None
    return state, epoch, sequence, event_age_ms + sample_age


def display_fields(focus, policy, monotonic_now):
    """Keep independent display-helper freshness and actual event identity."""
    sample_age = sample_age_ms(
        getattr(focus, "last_observation_time", None), monotonic_now)
    state, event_epoch, event_sequence, event_age = _event(
        getattr(focus, "display_state", None),
        getattr(focus, "display_event_age_ms", None),
        getattr(focus, "display_epoch", None),
        getattr(focus, "display_sequence", None), sample_age)
    ac, dc, source, idle = _policy(
        policy, getattr(focus, "last_input_idle_ms", None), sample_age)
    return {
        "state": state, "scope": "windows_console",
        "event_epoch": event_epoch, "event_sequence": event_sequence,
        "event_age_ms": event_age, "sample_age_ms": sample_age,
        "ac_timeout_seconds": ac, "dc_timeout_seconds": dc,
        "power_source": source, "last_input_idle_ms": idle,
    }


def system_fields(uptime, agent_version, build_sha):
    """No negative uptime or unverified release identity is emitted."""
    if (type(uptime) is not int or not 0 <= uptime <= MAX_UPTIME_SECONDS):
        raise ValueError("Invalid Windows system uptime")
    if type(agent_version) is not str or SEMVER.fullmatch(agent_version) is None:
        raise ValueError("Unverified agent version")
    if build_sha is not None and (
            type(build_sha) is not str or SHA40.fullmatch(build_sha) is None):
        build_sha = None
    return {"uptime_seconds": uptime, "agent_version": agent_version,
            "agent_build_sha": build_sha}


def make_snapshot(device_id, epoch, sequence, observed_at, foreground,
                  display, system):
    """Full v3 envelope only; never mutate or embed untrusted extra attributes."""
    if (type(device_id) is not str or DEVICE.fullmatch(device_id) is None
            or type(epoch) is not str or HEX32.fullmatch(epoch) is None
            or type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE
            or not finite(observed_at) or observed_at < 0):
        raise ValueError("Invalid v3 telemetry envelope")
    data = {"version": VERSION, "device_id": device_id, "epoch": epoch,
            "sequence": sequence, "observed_at": observed_at,
            "foreground": foreground, "display": display, "system": system}
    encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False)
    if len(encoded.encode("ascii")) > MAX_BYTES:
        raise ValueError("Oversized v3 telemetry packet")
    return encoded


def transition_key(packet, candidate=None):
    """Coalesce only unchanged observations; raw private PID NEVER sent.

    Distinct same-executable window focus changes must still issue a fresh
    packet: keep source identity in this local comparison, not in MQTT JSON.
    """
    fg, display = packet["foreground"], packet["display"]
    return (
        fg["state"], fg["process"], json.dumps(fg["signature"], sort_keys=True),
        candidate if fg["state"] == "foreground" else None,
        display["state"], display["event_epoch"], display["event_sequence"],
        display["ac_timeout_seconds"], display["dc_timeout_seconds"],
        display["power_source"], display["sample_age_ms"] is None,
    )
