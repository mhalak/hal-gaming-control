"""Windows diagnostic contract cannot grant gaming readiness or replay old health."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from custom_components.hal_gaming_control.diagnostic_protocol import decode_diagnostics
from custom_components.hal_gaming_control.foreground_source import ForegroundSource

FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "v1"
NONCE = (FIXTURES / "diagnostics-request.txt").read_text(encoding="utf-8").strip()
ROW = json.loads((FIXTURES / "diagnostics-response.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("change", [
    {"device_id": "pc2"}, {"nonce": "b" * 32}, {"version": True},
    {"active": [{"code": "arbitrary", "occurrences": 1}]},
    {"active": [{"code": "WIN_INVALID_SYSTEM_METADATA", "occurrences": True}]},
])
def test_invalid_response(change):
    with pytest.raises(ValueError):
        decode_diagnostics(json.dumps(ROW | change), "pc1", NONCE, retained=False)


def test_fresh_nonce_is_consumed_and_diagnostics_do_not_enable_game():
    source = ForegroundSource(Mock(), "pc1", [], Mock())
    source._connected = source._online = source._diagnostic_capable = True
    source._diagnostic_pending = (NONCE, 10)
    msg = Mock(topic=source.root + "/diagnostics/response",
               payload=json.dumps(ROW), retain=False)
    with patch("custom_components.hal_gaming_control.foreground_source.monotonic", return_value=11):
        source._diagnostic_response(msg)
        assert source.errors.snapshot()["state"] == "Invalid Windows system metadata"
        assert source.current(11) is None
        msg.payload = json.dumps(ROW | {"active": []})
        source._diagnostic_response(msg)
        assert source.errors.snapshot()["attributes"]["active_error_count"] == 1
    source.close()

async def test_production_poll_and_response_use_shared_read_only_contract():
    source = ForegroundSource(Mock(), "pc1", [], Mock())
    source._connected = source._online = True
    root = source.root
    source._v3_discovery(Mock(topic=root + "/discovery", payload=json.dumps({
        "protocol_version": 1, "device_id": "pc1", "name": "PC",
        "games": [], "actions": [], "unified_telemetry_protocol": 3,
        "diagnostics_protocol": 1})))
    mod = "custom_components.hal_gaming_control.foreground_source"
    with patch(mod + ".token_hex", return_value=NONCE), patch(mod + ".monotonic", return_value=10), \
            patch(mod + ".mqtt.async_publish", new_callable=AsyncMock) as publish:
        await source.async_poll_diagnostics()
        publish.assert_awaited_once_with(source.hass, root + "/diagnostics/request",
                                        NONCE, qos=0, retain=False)
    msg = Mock(topic=root + "/diagnostics/response",
               payload=json.dumps(ROW), retain=False)
    with patch(mod + ".monotonic", return_value=11):
        source._diagnostic_response(msg)
        result = source.errors.snapshot()
        assert result["state"] == "Invalid Windows system metadata"
        assert result["attributes"]["code"] == ROW["active"][0]["code"]
        assert result["attributes"]["occurrences"] == 1
        assert result["attributes"]["windows_diagnostics"] == "Current"
        assert source.current(11) is None
    source.close()


def test_old_agent_rediscovery_after_broker_reconnect_reports_unsupported():
    source = ForegroundSource(Mock(), "pc1", [], Mock())
    source._connected = source._online = True
    source._connection(False)
    source._connection(True)
    source._v3_discovery(Mock(topic=source.root + "/discovery", payload=json.dumps({
        "protocol_version": 1, "device_id": "pc1", "name": "PC",
        "games": [], "actions": [], "unified_telemetry_protocol": 3})))
    assert source.errors.remote_status == "Not supported"
    assert source.errors.snapshot(ready=True)["attributes"]["diagnostic_scope"] == "HA only"
    source.close()


def test_remote_fault_receipt_coalesces_and_recovers_without_touching_ha_errors():
    from custom_components.hal_gaming_control.error_registry import ErrorRegistry

    tick = [0]
    registry = ErrorRegistry(clock=lambda: tick[0], timestamp=lambda: str(tick[0]))
    registry.health = "Online"
    registry.report("HA_CLOCK_SKEW", clock_delta_seconds=2.61)
    registry.update_remote(ROW)
    first = registry.snapshot(ready=True)
    tick[0] = 5
    registry.update_remote(ROW | {"active": [dict(ROW["active"][0], occurrences=2)]})
    assert registry.snapshot(ready=True) == first
    tick[0] = 60
    registry.update_remote(ROW | {"active": [dict(ROW["active"][0], occurrences=3)]})
    after = registry.snapshot(ready=True)["attributes"]["active_errors"]
    remote = next(row for row in after if row["source"] == "Windows")
    assert remote["occurrences"] == 3
    assert remote["last_seen"] == "60"
    registry.remote_status = "Unavailable"
    assert registry.snapshot()["attributes"]["active_error_count"] == 2
    tick[0] = 61
    registry.update_remote(ROW | {"active": [], "last_resolved": dict(ROW["active"][0], occurrences=3)})
    assert registry.snapshot()["attributes"]["active_error_count"] == 1
    assert registry.snapshot()["state"] == "Clock synchronization error"
