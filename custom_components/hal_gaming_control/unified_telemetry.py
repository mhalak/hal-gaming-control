"""Strict read-only Windows Unified Telemetry v3 decoder (#176).

One complete, non-retained per-device snapshot is a source of *observations*,
never of control commands, HA budgets, enrollment or Windows updater results.
Pure validators share v2's trusted process/signature policy. Invalid or stale
data never fabricates idle, elapsed usage or a Screen Idle bonus.
"""
import json
import re
from time import monotonic, time

from .candidate_protocol import _valid_process, _valid_signature
from .foreground_snapshot import MAX_SEQUENCE, _finite, _unique_object
from .screen_idle import MAX_EVENT_AGE_MS

MAX_PACKET = 4096
MAX_AGE = 10.0
MAX_FUTURE = 2.0
MAX_OBSERVATION_AGE_MS = 86400000
MAX_FOREGROUND_AGE_MS = 10000
MAX_DISPLAY_AGE_MS = 8000
EPOCH = re.compile(r"[0-9a-f]{32}\Z")
DEVICE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
SEMVER = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\Z")
OUTER = {"version", "device_id", "epoch", "sequence", "observed_at",
         "foreground", "display", "system"}
FOREGROUND = {"state", "process", "signature", "sample_age_ms"}
DISPLAY = {"state", "scope", "event_epoch", "event_sequence", "event_age_ms",
           "sample_age_ms", "ac_timeout_seconds", "dc_timeout_seconds",
           "power_source", "last_input_idle_ms"}
SYSTEM = {"uptime_seconds", "agent_version", "agent_build_sha"}
LEGACY = {"in_game", "current_game", "active_game", "gaming_active", "focus_availability"}


def _age(value, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not int or not 0 <= value <= MAX_OBSERVATION_AGE_MS:
        raise ValueError("Invalid telemetry observation age")


def _foreground(value):
    if not isinstance(value, dict) or value.keys() != FOREGROUND:
        raise ValueError("Invalid foreground fields")
    state, process, signature = (
        value["state"], value["process"], value["signature"])
    age = value["sample_age_ms"]
    _age(age, nullable=state == "unknown")
    if state == "foreground":
        if age is None or not _valid_process(process) or not _valid_signature(
                process, signature):
            raise ValueError("Unsafe foreground identity")
    elif state in ("idle", "unknown"):
        if process is not None or signature is not None:
            raise ValueError("Idle/unknown cannot claim an executable")
        if state == "idle" and age is None:
            raise ValueError("Idle requires verified observation")
    else:
        raise ValueError("Invalid foreground state")


def _display_event(value):
    state = value["state"]
    receipt = (value["event_epoch"], value["event_sequence"],
               value["event_age_ms"])
    if state == "unknown":
        if any(v is not None for v in receipt):
            raise ValueError("Unknown display must not claim a notification")
    elif (not isinstance(receipt[0], str) or not EPOCH.fullmatch(receipt[0])
          or type(receipt[1]) is not int
          or not 1 <= receipt[1] <= MAX_SEQUENCE
          or type(receipt[2]) is not int
          or not 0 <= receipt[2] <= MAX_EVENT_AGE_MS):
        raise ValueError("Invalid console notification receipt")


def _display_policy(value):
    for key in ("ac_timeout_seconds", "dc_timeout_seconds"):
        v = value[key]
        if v is not None and (type(v) is not int or not 0 <= v <= 0xffffffff):
            raise ValueError("Invalid display power timeout")
    if value["power_source"] not in ("ac", "battery", "unknown"):
        raise ValueError("Invalid display power source")
    _age(value["last_input_idle_ms"], nullable=True)


def _display(value):
    if not isinstance(value, dict) or value.keys() != DISPLAY:
        raise ValueError("Invalid display fields")
    state = value["state"]
    if state not in ("on", "dim", "off", "unknown"):
        raise ValueError("Invalid console display state")
    if value["scope"] != "windows_console":
        raise ValueError("Invalid console display scope")
    age = value["sample_age_ms"]
    _age(age, nullable=True)
    if state != "unknown" and age is None:
        raise ValueError("Console evidence requires a sample")
    _display_event(value)
    _display_policy(value)


def _system(value):
    if not isinstance(value, dict) or value.keys() != SYSTEM:
        raise ValueError("Invalid system fields")
    if (type(value["uptime_seconds"]) is not int
            or not 0 <= value["uptime_seconds"] <= (1 << 63) - 1
            or not isinstance(value["agent_version"], str)
            or not SEMVER.fullmatch(value["agent_version"])):
        raise ValueError("Invalid system telemetry")
    sha = value["agent_build_sha"]
    if sha is not None and (not isinstance(sha, str) or not SHA.fullmatch(sha)):
        raise ValueError("Invalid build SHA")


def _parse_packet(payload, retained):
    if (retained is not False or not isinstance(payload, (str, bytes))
            or not 0 < len(payload) <= MAX_PACKET
            or (isinstance(payload, str)
                and len(payload.encode("utf-8")) > MAX_PACKET)):
        raise ValueError("Missing non-retained unified telemetry")
    try:
        return json.loads(
            payload, object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Malformed unified telemetry") from exc


def _validate_identity(packet, device_id):
    if (not isinstance(packet, dict)
            or not (packet.keys() == OUTER
                    or packet.keys() == OUTER | {"legacy"})
            or type(packet["version"]) is not int or packet["version"] != 3
            or not isinstance(packet["device_id"], str)
            or not DEVICE.fullmatch(packet["device_id"])
            or packet["device_id"] != device_id):
        raise ValueError("Invalid unified telemetry identity")


class TelemetryTimestampError(ValueError):
    """Preserve rejection semantics while exposing a safe structured reason."""

    def __init__(self, code, delta=None):
        super().__init__("Invalid unified telemetry timestamp")
        self.code = code
        self.delta = delta


def _validate_stamp(packet, wall_now):
    if (not isinstance(packet["epoch"], str)
            or not EPOCH.fullmatch(packet["epoch"])
            or type(packet["sequence"]) is not int
            or not 1 <= packet["sequence"] <= MAX_SEQUENCE):
        raise ValueError("Invalid unified telemetry ordering")
    stamp = packet["observed_at"]
    if not _finite(stamp) or stamp < 0 or not _finite(wall_now):
        raise TelemetryTimestampError("HA_INVALID_TELEMETRY")
    if not -MAX_FUTURE <= wall_now - stamp < MAX_AGE:
        delta = stamp - wall_now
        raise TelemetryTimestampError(
            "HA_CLOCK_SKEW" if delta > MAX_FUTURE else "HA_TELEMETRY_STALE",
            round(max(-86400, min(86400, delta)), 2))


def _validate_legacy(packet):
    if "legacy" not in packet:
        return
    legacy = packet["legacy"]
    if (not isinstance(legacy, dict) or legacy.keys() != LEGACY
            or not all(isinstance(v, str) and len(v) <= 128
                       for v in legacy.values())):
        raise ValueError("Invalid temporary legacy diagnostics")


def _foreground_stale(packet, wall_now):
    age = packet["foreground"]["sample_age_ms"]
    return (age is None or age >= MAX_FOREGROUND_AGE_MS
            or wall_now - (packet["observed_at"] - age / 1000) >= MAX_AGE)


def _display_stale(packet, wall_now):
    display = packet["display"]
    age = display["sample_age_ms"]
    # The last Windows ON/OFF event may be hours old while the interactive
    # helper still provides a fresh observation of the current screen state.
    # Only sample age and message freshness determine staleness here.
    # DisplayGate separately expires evidence when live packets stop arriving.
    return (age is None or age >= MAX_DISPLAY_AGE_MS
            or wall_now - (packet["observed_at"] - age / 1000)
            >= MAX_DISPLAY_AGE_MS / 1000)


def _normalized_packet(packet, wall_now):
    fg, display = dict(packet["foreground"]), dict(packet["display"])
    # Fresh uptime must not manufacture a newer helper sample.
    if _foreground_stale(packet, wall_now):
        fg.update(state="unknown", process=None, signature=None,
                  sample_age_ms=None)
    if _display_stale(packet, wall_now):
        display.update(state="unknown", event_epoch=None,
                       event_sequence=None, event_age_ms=None)
    return {**packet, "foreground": fg, "display": display}


def decode_telemetry(payload, device_id, *, retained, wall_now):
    """One complete device-scoped, timestamped, non-retained v3 snapshot."""
    packet = _parse_packet(payload, retained)
    _validate_identity(packet, device_id)
    _validate_stamp(packet, wall_now)
    _foreground(packet["foreground"])
    _display(packet["display"])
    _system(packet["system"])
    _validate_legacy(packet)
    return _normalized_packet(packet, wall_now)


def foreground_v2(packet):
    """Reuse unchanged composite-key accounting with the publisher's order."""
    fg = packet["foreground"]
    observed = packet["observed_at"]
    if fg["sample_age_ms"] is not None:
        observed -= fg["sample_age_ms"] / 1000
    return json.dumps({
        "version": 2, "device_id": packet["device_id"],
        "epoch": packet["epoch"], "sequence": packet["sequence"],
        "observed_at": observed, "state": fg["state"],
        "process": fg["process"], "signature": fg["signature"],
    }, separators=(",", ":"))


def display_v2(packet):
    """Pass independent helper event identity to existing Screen Idle gate."""
    display = packet["display"]
    return json.dumps({
        "version": 2, "device_id": packet["device_id"],
        "observed_at": packet["observed_at"],
        "display_state": display["state"],
        "display_epoch": display["event_epoch"],
        "display_sequence": display["event_sequence"],
        "display_event_age_ms": display["event_age_ms"],
        "display_scope": display["scope"],
        "ac_timeout_seconds": display["ac_timeout_seconds"],
        "dc_timeout_seconds": display["dc_timeout_seconds"],
        "power_source": display["power_source"],
        "last_input_idle_ms": display["last_input_idle_ms"],
    }, separators=(",", ":"))


class TelemetryOrder:
    """Per-PC anti-replay watermark spanning publisher reconnects.

    An explicit publisher offline LWT retires its epoch. A subscriber-only
    disconnect invalidates liveness but preserves ordering watermarks so
    a still-connected publisher can resume with newer fresh observations.
    """
    def __init__(self):
        self.epoch = None
        self.sequence = 0
        self.observed_at = None
        self.retired = {}
        self.received = None

    def suspend(self, *, retire=True):
        if retire and self.epoch is not None:
            self.retired[self.epoch] = float("inf")
        self.received = None

    def accept(self, packet, *, monotonic_now):
        if not _finite(monotonic_now):
            return False
        if self.received is not None and monotonic_now < self.received:
            self.suspend()
            return False
        epoch, sequence, stamp = (
            packet["epoch"], packet["sequence"], packet["observed_at"])
        if epoch in self.retired:
            return False
        if self.observed_at is not None:
            if epoch == self.epoch:
                if sequence <= self.sequence or stamp <= self.observed_at:
                    return False
            elif stamp <= self.observed_at:
                return False
            if epoch != self.epoch:
                self.retired[self.epoch] = float("inf")
                # The global timestamp watermark already rejects older
                # recordings. Keep only a bounded list of retired epochs.
                while len(self.retired) > 64:
                    self.retired.pop(next(iter(self.retired)))
        self.epoch, self.sequence, self.observed_at = epoch, sequence, stamp
        self.received = monotonic_now
        return True
