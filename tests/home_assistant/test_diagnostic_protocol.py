"""Windows diagnostic contract cannot grant gaming readiness or replay old health."""
import json
from unittest.mock import Mock, patch

import pytest
from custom_components.hal_gaming_control.diagnostic_protocol import decode_diagnostics
from custom_components.hal_gaming_control.foreground_source import ForegroundSource

NONCE = "a" * 32
ROW = {"version": 1, "device_id": "pc1", "nonce": NONCE,
       "active": [{"code": "WIN_INVALID_SYSTEM_METADATA", "occurrences": 7}],
       "last_resolved": None}


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
