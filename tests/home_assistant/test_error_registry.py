"""Error registry and single diagnostic sensor contract (#291)."""
import json
from unittest.mock import Mock, patch

import pytest
from homeassistant.const import EntityCategory

from custom_components.hal_gaming_control.error_registry import ErrorRegistry
from custom_components.hal_gaming_control.sensor import ErrorStateSensor
from custom_components.hal_gaming_control.unified_telemetry import (
    TelemetryTimestampError, decode_telemetry,
)
from custom_components.hal_gaming_control.foreground_source import ForegroundSource

DEVICE = "pc1"
P = "RobloxPlayerBeta.exe"
E1 = "a" * 32
E2 = "b" * 32


def sample(ts=100., seq=1, *, device=DEVICE, epoch=E1,
           fg="foreground", screen="on", fg_age=20, display_age=20):
    return {
        "version": 3, "device_id": device, "epoch": epoch, "sequence": seq,
        "observed_at": ts,
        "foreground": {"state": fg,
                       "process": P if fg == "foreground" else None,
                       "signature": None, "sample_age_ms": fg_age},
        "display": {
            "state": screen, "scope": "windows_console",
            "event_epoch": E2 if screen != "unknown" else None,
            "event_sequence": 1 if screen != "unknown" else None,
            "event_age_ms": 500 if screen != "unknown" else None,
            "sample_age_ms": display_age,
            "ac_timeout_seconds": 600, "dc_timeout_seconds": 300,
            "power_source": "ac", "last_input_idle_ms": 125000},
        "system": {"uptime_seconds": 9000, "agent_version": "0.2.12",
                   "agent_build_sha": None},
    }



def test_registry_priority_coalescing_recovery_and_isolation():
    tick = [0]
    registry = ErrorRegistry(clock=lambda: tick[0], timestamp=lambda: str(tick[0]))
    other = ErrorRegistry()
    registry.health = "Online"
    assert registry.snapshot(ready=True)["state"] == "OK"
    registry.report("HA_CLOCK_SKEW", clock_delta_seconds=2.61)
    first = registry.snapshot()
    for _ in range(142):
        registry.report("HA_CLOCK_SKEW", clock_delta_seconds=2.61)
    assert registry.snapshot() == first
    tick[0] = 60
    registry.report("HA_CLOCK_SKEW", clock_delta_seconds=2.61)
    assert registry.snapshot()["attributes"]["occurrences"] == 144
    registry.report("HA_STORAGE_FAILURE")
    assert registry.snapshot()["state"] == "Storage failure"
    assert registry.snapshot()["attributes"]["active_error_count"] == 2
    assert other.snapshot()["attributes"]["active_error_count"] == 0
    registry.resolve("HA_STORAGE_FAILURE")
    assert registry.snapshot()["state"] == "Clock synchronization error"
    registry.resolve("HA_CLOCK_SKEW")
    assert registry.snapshot(ready=True)["state"] == "OK"
    assert registry.snapshot()["attributes"]["last_resolved_error"]["occurrences"] == 144


@pytest.mark.parametrize("delta, code", [
    (2.61, "HA_CLOCK_SKEW"), (-10, "HA_TELEMETRY_STALE"),
])
def test_timestamp_reason_preserves_existing_validation(delta, code):
    with pytest.raises(TelemetryTimestampError) as err:
        decode_telemetry(json.dumps(sample()), "pc1", retained=False,
                         wall_now=100 - delta)
    assert err.value.code == code
    assert err.value.delta == delta


@pytest.mark.parametrize("delta", [2, -9.99, 0])
def test_timestamp_acceptance_unchanged(delta):
    assert decode_telemetry(json.dumps(sample()), "pc1", retained=False,
                            wall_now=100 - delta)["sequence"] == 1


def test_clock_rejection_and_recovery_are_visible_while_game_unknown():
    source = ForegroundSource(Mock(), "pc1", [], Mock())
    source._connected = source._online = source.v3_capable = True
    source._availability_seen = True
    msg = Mock(topic=source.root + "/state/telemetry", retain=False)
    msg.payload = json.dumps(sample(ts=100))
    module = "custom_components.hal_gaming_control.foreground_source"
    with patch(module + ".time", return_value=97.39), patch(module + ".monotonic", return_value=10):
        source._telemetry_snapshot(msg)
    assert source.current(10) is None
    snapshot = source.errors.snapshot()
    assert snapshot["state"] == "Clock synchronization error"
    assert snapshot["attributes"]["clock_delta_seconds"] == 2.61
    coordinator = Mock(device_id="pc1", data={"ready": False, "error_state": snapshot})
    coordinator.entry.data = {"name": "PC"}
    sensor = ErrorStateSensor(coordinator)
    assert sensor.available
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
    assert sensor.unique_id == "pc1_error_state"
    assert sensor.native_value == "Clock synchronization error"
    assert sensor.extra_state_attributes["code"] == "HA_CLOCK_SKEW"
    msg.payload = json.dumps(sample(ts=104, seq=2))
    with patch(module + ".time", return_value=104), patch(module + ".monotonic", return_value=14):
        source._telemetry_snapshot(msg)
    assert source.errors.snapshot()["attributes"]["active_error_count"] == 0
    source.close()


def test_missing_stream_offline_and_broker_disconnect_are_distinct():
    source = ForegroundSource(Mock(), "pc1", [], Mock())
    source._connected = True
    assert source.current(0) is None
    assert source.errors.snapshot()["state"] == "Waiting for telemetry"
    source._availability(Mock(topic=source.root + "/availability", payload="online"))
    source.current(1)
    source.current(11)
    assert source.errors.snapshot()["state"] == "Telemetry missing"
    source._availability(Mock(topic=source.root + "/availability", payload="offline"))
    source.current(12)
    assert source.errors.snapshot()["state"] == "Offline"
    source._connection(False)
    source.current(13)
    assert source.errors.snapshot()["state"] == "MQTT disconnected"
    source.close()
