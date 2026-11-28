"""Read-only readiness evidence and bounded per-device incident history."""
from collections import deque
from copy import deepcopy

# Stable reasons are independent of localized sensor state text.
REASONS = {
    "HEALTHY": "Verified gameplay and Windows diagnostics are current.",
    "INITIALIZING": "MQTT connection or coordinator has not initialized.",
    "WAITING_AVAILABILITY": "No device availability report has been observed.",
    "OFFLINE": "Device availability reports offline.",
    "WAITING_DISCOVERY": "Waiting for supported unified v3 discovery.",
    "WAITING_FIRST_PACKET": "No accepted unified v3 packet in this connection.",
    "TELEMETRY_TIMEOUT": "Last accepted unified v3 packet is outside the freshness window.",
    "ORDER_REJECTED": "A received packet failed the ordering gate.",
    "POST_SCREEN_ON": "Verified display ON; waiting for a newer foreground observation.",
    "DISPLAY_UNCERTAIN": "Previous OFF evidence has not been cleared by verified ON and foreground.",
    "FOREGROUND_UNKNOWN": "Foreground observation is unknown or cannot identify a tracked application safely.",
    "FOREGROUND_EXPIRED": "Foreground sample is absent or exceeds its freshness limit.",
    "FOREGROUND_NOT_READY": "Foreground accounting has no current verified sample.",
    "REMOTE_UNSUPPORTED": "Agent has not advertised the supported diagnostics protocol.",
    "REMOTE_WAITING": "Waiting for a current Windows diagnostic reply.",
    "REMOTE_EXPIRED": "Last Windows diagnostic reply is outside the freshness window.",
}


def age_seconds(now, then):
    return round(now - then, 3) if then is not None and now >= then else None


def readiness_reason(source, observed, ready):
    """Classify existing gates, without treating expected waits as faults."""
    if not source._connected:
        return "INITIALIZING"
    if not source._online:
        return "OFFLINE" if source._availability_seen else "WAITING_AVAILABILITY"
    if not source.v3_capable:
        return "WAITING_DISCOVERY"
    last = source.telemetry_order.received
    if last is None:
        return "WAITING_FIRST_PACKET"
    if not 0 <= observed - last < 10:
        return "ORDER_REJECTED" if source._evidence_rejection == "ORDER_REJECTED" else "TELEMETRY_TIMEOUT"
    if not ready:
        if source._needs_post_on:
            return "POST_SCREEN_ON"
        if source._screen_off_latched:
            return "DISPLAY_UNCERTAIN"
        sample = source._evidence_sample
        if sample.get("reported_foreground_state") == "unknown":
            return "FOREGROUND_UNKNOWN"
        if sample.get("foreground_sample_stale"):
            return "FOREGROUND_EXPIRED"
        return "FOREGROUND_NOT_READY"
    if source.errors.remote_status == "Current":
        return "HEALTHY"
    if source.errors.remote_status == "Not supported":
        return "REMOTE_UNSUPPORTED"
    return "REMOTE_EXPIRED" if source._diagnostic_received is not None else "REMOTE_WAITING"


def transition_evidence(source, observed):
    """Only validated, allowlisted scalars; no payload, app name or opaque ID."""
    return {
        **source._evidence_sample,
        "mqtt_connected": source._connected,
        "availability_seen": source._availability_seen,
        "device_online": source._online,
        "v3_capable": source.v3_capable,
        "last_received_age_seconds": age_seconds(observed, source._evidence_received),
        "last_accepted_age_seconds": age_seconds(observed, source._evidence_accepted),
        "receive_gap_seconds": source._evidence_gap,
        "freshness_limit_seconds": 10,
        "future_tolerance_seconds": 2,
        "foreground_freshness_limit_ms": 10000,
        "display_freshness_limit_ms": 8000,
        "display_state": source.display.current(observed),
        "post_on_pending": source._needs_post_on,
        "screen_off_latched": source._screen_off_latched,
        "last_rejection": source._evidence_rejection,
        "epoch_changes": source._evidence_epoch_changes,
        "ordering_rejections": source._evidence_order_rejections,
        "windows_diagnostics": source.errors.remote_status,
        "diagnostic_reply_age_seconds": age_seconds(observed, source._diagnostic_received),
    }


class IncidentHistory:
    """Freeze evidence on semantic change; retain the last eight incidents in RAM."""

    def __init__(self, clock, timestamp):
        self._clock, self._timestamp = clock, timestamp
        self._current = None
        self._started = None
        self._completed = deque(maxlen=8)
        self._counts = {}
        self._durations = {}

    def capture(self, state, reason, evidence, description):
        key = (state, reason)
        if self._current is None or key != self._current["key"]:
            self._transition(key, evidence, description)
        return deepcopy({
            "reason_code": reason,
            "reason_description": self._current["description"],
            "transition_evidence": self._current["evidence"],
            "state_since": self._current["started_at"],
            "last_incident": self._completed[-1] if self._completed else None,
            "recent_incidents": list(self._completed),
            "reason_counts": self._counts,
            "reason_duration_seconds": self._durations,
            "incident_history_scope": "Since integration load",
        })

    def _transition(self, key, evidence, description):
        tick, timestamp = self._clock(), self._timestamp()
        prior = self._current
        if prior is not None and prior["key"][0] != "OK":
            reason = prior["key"][1]
            duration = age_seconds(tick, self._started)
            self._completed.append({
                "state": prior["key"][0], "reason_code": reason,
                "description": prior["description"], "started_at": prior["started_at"],
                "resolved_at": timestamp, "duration_seconds": duration,
                "resolved_by": key[1], "evidence": prior["evidence"],
                "recovery_evidence": deepcopy(evidence),
            })
            if duration is not None:
                self._durations[reason] = round(self._durations.get(reason, 0) + duration, 3)
        self._current = {
            "key": key, "started_at": timestamp, "evidence": deepcopy(evidence),
            "description": description or REASONS.get(key[1], key[1]),
        }
        self._started = tick
        if key[0] != "OK":
            self._counts[key[1]] = self._counts.get(key[1], 0) + 1
