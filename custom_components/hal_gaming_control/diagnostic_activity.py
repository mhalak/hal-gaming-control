"""Concise, read-only Logbook cause for a semantic diagnostic transition."""
from math import isfinite

EVENT = "hal_gaming_control_diagnostic_transition"


def _measurement(evidence, key, label):
    value = evidence.get(key)
    if type(value) in (int, float) and isfinite(value):
        return f"{label}: {value:g} s"
    return None


def transition_data(entity_id, old, snapshot):
    """Record only actual state/reason changes, not periodic counter updates."""
    if old is None:
        return None
    state, attrs = snapshot["state"], snapshot["attributes"]
    reason = attrs.get("reason_code", "INITIALIZING")
    if old.state == state and old.attributes.get("reason_code", "INITIALIZING") == reason:
        return None
    description = attrs.get("reason_description", "Diagnostic evidence is not available.")
    evidence = attrs.get("transition_evidence", {})
    parts = [description]
    for key, label in (
        ("last_received_age_seconds", "Last packet received"),
        ("last_accepted_age_seconds", "Last packet accepted"),
        ("clock_delta_seconds", "Publisher clock delta"),
    ):
        if measured := _measurement(evidence, key, label):
            parts.append(measured)
    incident = attrs.get("last_incident")
    if state == "OK" and incident:
        if duration := _measurement(incident, "duration_seconds", "Previous interval duration"):
            parts.append(duration)
    return {
        "entity_id": entity_id, "previous_state": old.state, "state": state,
        "reason_code": reason, "description": description,
        "message": "; ".join(parts),
    }
