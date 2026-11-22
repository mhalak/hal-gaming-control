"""Validate native MQTT Uptime discovery's real Jinja rendering and identity.

The Windows publisher owns this one existing HA MQTT discovery payload.
The template must emit a bounded numeric uptime for this PC or UNKNOWN,
never silently accept another PC's data or an invalid number.
"""
from jinja2 import Environment
import pytest

from windows_agent.gaming_control.discovery import discovery


def _template(device_id="pc1", enabled=True):
    configs = discovery(device_id, "Gaming PC", unified_enabled=enabled)
    key = f"homeassistant/sensor/smarthouse_gaming_{device_id}_uptime/config"
    return configs[key], Environment().from_string(configs[key]["value_template"])


def test_exact_existing_native_uptime_unique_id_with_v3_json():
    payload, tpl = _template()
    assert payload["unique_id"] == "smarthouse_gaming_pc1_uptime"
    assert payload["state_topic"] == "SmartHouse/Gaming/pc1/state/telemetry"
    assert payload["expire_after"] == 10
    sample = {
        "version": 3, "device_id": "pc1",
        "system": {"uptime_seconds": 45630}
    }
    assert tpl.render(value_json=sample).strip() == "45630"
    assert tpl.render(value_json=sample | {"system": {"uptime_seconds": 0}}).strip() == "0"
    assert tpl.render(value_json=sample | {"system": {
        "uptime_seconds": 9223372036854775807}}).strip() == "9223372036854775807"


@pytest.mark.parametrize("mutation", [
    {"version": 2}, {"version": 4}, {"device_id": "pc2"},
    {"system": {}}, {"system": {"uptime_seconds": -1}},
    {"system": {"uptime_seconds": True}},
    {"system": {"uptime_seconds": None}},
    {"system": {"uptime_seconds": "9000"}},
    {"system": {"uptime_seconds": 9223372036854775808}},
])
def test_native_uptime_template_rejects_malformed_wrong_device_and_bool(mutation):
    _, tpl = _template()
    source = {
        "version": 3, "device_id": "pc1",
        "system": {"uptime_seconds": 42}
    }
    assert tpl.render(value_json=source | mutation).strip() == "unknown"


def test_v2_discovery_rolls_back_without_changing_unique_id():
    v3 = discovery("pc1", "Gaming PC", unified_enabled=True)
    v2 = discovery("pc1", "Gaming PC", unified_enabled=False)
    assert set(v3) == set(v2)
    key = "homeassistant/sensor/smarthouse_gaming_pc1_uptime/config"
    assert v3[key]["unique_id"] == v2[key]["unique_id"]
    assert v2[key]["state_topic"] == "SmartHouse/Gaming/pc1/state/uptime"
    assert "expire_after" not in v2[key]
    assert "value_template" not in v2[key]
