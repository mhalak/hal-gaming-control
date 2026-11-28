"""Read-only diagnostic response contract, independent of remote wall time."""
import json
import re

from .foreground_snapshot import _unique_object

WINDOWS_ERRORS = {
    "WIN_CLOCK_DISCONTINUITY": ("warning", "Windows clock discontinuity", "Check Windows time synchronization."),
    "WIN_INVALID_SYSTEM_METADATA": ("error", "Invalid Windows system metadata", "Check the agent version and logs."),
    "WIN_INVALID_SNAPSHOT": ("error", "Invalid Windows telemetry snapshot", "Check the agent logs."),
    "WIN_TELEMETRY_PUBLISH_FAILED": ("error", "Windows telemetry publish failed", "Check MQTT connectivity."),
}
NONCE = re.compile(r"[0-9a-f]{32}")


def _record(row):
    if (not isinstance(row, dict) or set(row) != {"code", "occurrences"}
            or not isinstance(row["code"], str) or row["code"] not in WINDOWS_ERRORS
            or type(row["occurrences"]) is not int
            or not 1 <= row["occurrences"] <= 2**31 - 1):
        raise ValueError("Invalid diagnostic record")
    return row


def decode_diagnostics(payload, device_id, nonce, *, retained):
    if (retained is not False or not isinstance(payload, (str, bytes))
            or not 0 < len(payload) <= 2048 or not isinstance(nonce, str)
            or not NONCE.fullmatch(nonce)):
        raise ValueError("Invalid diagnostics response")
    row = json.loads(payload, object_pairs_hook=_unique_object)
    if (not isinstance(row, dict) or set(row) != {
            "version", "device_id", "nonce", "active", "last_resolved"}
            or type(row["version"]) is not int or row["version"] != 1
            or row["device_id"] != device_id or row["nonce"] != nonce
            or not isinstance(row["active"], list)
            or len(row["active"]) > len(WINDOWS_ERRORS)):
        raise ValueError("Invalid diagnostics identity")
    active = [_record(item) for item in row["active"]]
    if len({item["code"] for item in active}) != len(active):
        raise ValueError("Duplicate diagnostic code")
    if row["last_resolved"] is not None:
        _record(row["last_resolved"])
    return row
