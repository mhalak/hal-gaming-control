import json
import pytest
from custom_components.hal_gaming_control.update_protocol import catalog_url, catalog_version, make_request, parse_status

def test_catalog():
    assert catalog_url("https://server.example/updates/approved.json")
    assert catalog_version(b'{"version":"0.2.0"}') == "0.2.0"
    for url in ("http://server/a", "https://user:pass@server/a", "https://server/a?token=abc"):
        with pytest.raises(ValueError):
            catalog_url(url)
    with pytest.raises(ValueError):
        catalog_version(b'{"version":"0.2.0","url":"https://evil.example"}')

def test_request():
    request = make_request("0.1.0", "0.2.0", 1000)
    assert request["expires_at"] == 1120
    assert parse_status(json.dumps({"request_id":request["request_id"],"version":"0.2.0","status":"success","timestamp":1100}))["status"] == "success"
    for version in ("0.1.0", "0.0.9", "../bad"):
        with pytest.raises(ValueError):
            make_request("0.1.0", version, 1000)
