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
from .screen_idle import MAX_EVENT_AGE_MS, STATE_TTL

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


def _display(value):
    if not isinstance(value, dict) or value.keys() != DISPLAY:
        raise ValueError("Invalid display fields")
    state = value["state"]
    if state not in ("on", "dim", "off", "unknown") or value["scope"] != "windows_console":
        raise ValueError("Invalid console display state")
    age = value["sample_age_ms"]
    _age(age, nullable=True)
    if state != "unknown" and age is None:
        raise ValueError("Console evidence requires a sample")
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
    for key in ("ac_timeout_seconds", "dc_timeout_seconds"):
        v = value[key]
        if v is not None and (type(v) is not int or not 0 <= v <= 0xffffffff):
            raise ValueError("Invalid display power timeout")
    if value["power_source"] not in ("ac", "battery", "unknown"):
        raise ValueError("Invalid display power source")
    _age(value["last_input_idle_ms"], nullable=True)


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


def decode_telemetry(payload, device_id, *, retained, wall_now):
    """Decode one complete v3 snapshot; reject foreign, retained and stale data.

    Subfield samples that were valid but have since aged out are normalized
    to UNKNOWN, not silently treated as current confirmed observations.
    """
    if (retained is not False or not isinstance(payload, (str, bytes))
            or not 0 < len(payload) <= MAX_PACKET):
        raise ValueError("Missing non-retained unified telemetry")
    try:
        obj = json.loads(payload, object_pairs_hook=_unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Malformed unified telemetry") from exc
    if (not isinstance(obj, dict) or not
            (obj.keys() == OUTER or obj.keys() == OUTER | {"legacy"})
            or type(obj["version"]) is not int or obj["version"] != 3
            or not isinstance(obj["device_id"], str)
            or not DEVICE.fullmatch(obj["device_id"])
            or obj["device_id"] != device_id
            or not isinstance(obj["epoch"], str)
            or not EPOCH.fullmatch(obj["epoch"])
            or type(obj["sequence"]) is not int
            or not 1 <= obj["sequence"] <= MAX_SEQUENCE
            or not _finite(obj["observed_at"]) or obj["observed_at"] < 0
            or not _finite(wall_now) or not
            -MAX_FUTURE <= wall_now - obj["observed_at"] < MAX_AGE):
        raise ValueError("Invalid unified telemetry envelope")
    _foreground(obj["foreground"])
    _display(obj["display"])
    _system(obj["system"])
    if "legacy" in obj:
        legacy = obj["legacy"]
        if (not isinstance(legacy, dict) or legacy.keys() != LEGACY
                or not all(isinstance(v, str) and len(v) <= 128
                           for v in legacy.values())):
            raise ValueError("Invalid temporary legacy diagnostics")
    fg, display = dict(obj["foreground"]), dict(obj["display"])
    # The upstream helper may have stopped providing fresh evidence while the
    # agent keeps reporting its own new uptime; no extrapolation is allowed.
    if (fg["sample_age_ms"] is None
            or fg["sample_age_ms"] >= MAX_FOREGROUND_AGE_MS
            or wall_now - (obj["observed_at"] - fg["sample_age_ms"] / 1000)
               >= MAX_AGE):
        fg.update(state="unknown", process=None, signature=None,
                  sample_age_ms=None)
    if (display["sample_age_ms"] is None
            or display["sample_age_ms"] >= MAX_DISPLAY_AGE_MS
            or (display["event_age_ms"] is not None
                and display["event_age_ms"] >= STATE_TTL * 1000)
            or (display["sample_age_ms"] is not None
                and wall_now - (obj["observed_at"]
                                - display["sample_age_ms"] / 1000) >= MAX_DISPLAY_AGE_MS / 1000)):
        display.update(state="unknown", event_epoch=None,
                       event_sequence=None, event_age_ms=None)
    return {**obj, "foreground": fg, "display": display}


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

    A broker loss or offline LWT retires the current epoch, requiring a new
    publisher session to resume; clock monotonicity is checked separately.
    """
    def __init__(self):
        self.epoch = None
        self.sequence = 0
        self.observed_at = None
        self.retired = {}
        self.received = None

    def suspend(self):
        if self.epoch is not None:
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
                if sequence <= self.sequence or stamp < self.observed_at:
                    return False
            elif stamp <= self.observed_at:
                return False
            if epoch != self.epoch:
                self.retired[self.epoch] = float("inf")
        self.epoch, self.sequence, self.observed_at = epoch, sequence, stamp
        self.received = monotonic_now
        return True
