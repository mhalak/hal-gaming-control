"""Bounded per-device HA diagnostic registry."""
from datetime import datetime, timezone
from time import monotonic

from .diagnostic_protocol import WINDOWS_ERRORS

CATALOG = {
    "HA_STORAGE_FAILURE": ("critical", "Storage failure", "Check HA storage and logs."),
    "HA_INVALID_BUDGET": ("error", "Invalid gaming budget data", "Check bonus journal and logs."),
    "HA_CLOCK_SKEW": ("error", "Clock synchronization error", "Synchronize Windows and HA clocks."),
    "HA_TELEMETRY_STALE": ("error", "Stale telemetry", "Check clocks and MQTT delivery."),
    "HA_INVALID_TELEMETRY": ("error", "Invalid telemetry", "Check agent version and logs."),
    "HA_PROTOCOL_UNSUPPORTED": ("error", "Unsupported telemetry protocol", "Check agent version and discovery."),
    "HA_TELEMETRY_MISSING": ("error", "Telemetry missing", "Check Windows agent and MQTT connection."),
    "HA_MQTT_DISCONNECTED": ("error", "MQTT disconnected", "Check MQTT broker connectivity."),
}
PRIORITY = {"critical": 0, "error": 1, "warning": 2}


class ErrorRegistry:
    """Stable codes, coalesced counters and one bounded resolved record."""

    def __init__(self, *, clock=monotonic, timestamp=None):
        self._clock = clock
        self._timestamp = timestamp or (lambda: datetime.now(timezone.utc).isoformat())
        self._active = {}
        self._published = {}
        self._last_publish = {}
        self._last_resolved = None
        self.health = "Waiting for telemetry"
        self.remote_status = "Not supported"
        self._remote = {}
        self._remote_resolved = None

    def report(self, code, *, clock_delta_seconds=None):
        severity, title, action = CATALOG[code]
        now, tick = self._timestamp(), self._clock()
        row = self._active.setdefault(code, {
            "code": code, "severity": severity, "source": "Home Assistant",
            "title": title, "description": title, "suggested_action": action,
            "first_seen": now, "occurrences": 0})
        row["occurrences"] += 1
        row["last_seen"] = now
        if clock_delta_seconds is not None:
            row["clock_delta_seconds"] = clock_delta_seconds
        if code not in self._published or tick - self._last_publish[code] >= 60:
            self._published[code] = dict(row)
            self._last_publish[code] = tick

    def resolve(self, code):
        row = self._active.pop(code, None)
        if row is not None:
            self._published.pop(code, None)
            self._last_publish.pop(code, None)
            self._last_resolved = dict(row, resolved_at=self._timestamp())

    def update_remote(self, packet):
        """Replace only Windows records after a fresh, validated response."""
        now = self._timestamp()
        active = {}
        for item in packet["active"]:
            code = item["code"]
            severity, title, action = WINDOWS_ERRORS[code]
            prior = self._remote.get(code, {})
            active[code] = {
                "code": code, "severity": severity, "source": "Windows",
                "title": title, "description": title, "suggested_action": action,
                "first_seen": prior.get("first_seen", now), "last_seen": now,
                "occurrences": item["occurrences"],
            }
        self._remote = active
        resolved = packet["last_resolved"]
        if resolved != self._remote_resolved:
            self._remote_resolved = dict(resolved) if resolved else None
        self.remote_status = "Current"

    def snapshot(self, *, ready=False):
        remote = [dict(row, evidence=self.remote_status) for row in self._remote.values()]
        active = sorted([*self._published.values(), *remote],
                        key=lambda row: (PRIORITY[row["severity"]], row["first_seen"], row["code"]))
        primary = active[0] if active else None
        state = (primary["title"] if primary else
                 "OK" if ready and self.health == "Online" and self.remote_status == "Current" else
                 "Diagnostics unavailable" if ready and self.health == "Online" else
                 "Waiting for telemetry" if self.health == "Online" else self.health)
        attributes = {
            "diagnostic_scope": "HA and Windows" if self.remote_status != "Not supported" else "HA only",
            "windows_diagnostics": self.remote_status,
            "windows_last_resolved_error": (dict(self._remote_resolved) if self._remote_resolved else None),
            "connection_state": self.health,
            "active_error_count": len(active),
            "active_errors": [dict(row) for row in active],
            "last_resolved_error": dict(self._last_resolved) if self._last_resolved else None,
        }
        if primary:
            attributes.update(primary)
        return {"state": state, "attributes": attributes}
