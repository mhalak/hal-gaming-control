"""Breaking-change contract: only the new HA domain ships in preview 0.7.0."""
import json
from pathlib import Path

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = ROOT / "custom_components"


def test_only_hal_gaming_control_integration_is_installed():
    assert (COMPONENTS / "hal_gaming_control" / "manifest.json").is_file()
    assert not (COMPONENTS / "smarthouse_gaming").exists()
    assert not (COMPONENTS / "parental").exists()
    assert not (COMPONENTS / "parental_control").exists()
    manifest = json.loads((COMPONENTS / "hal_gaming_control" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "hal_gaming_control"
    assert manifest["version"] == "0.13.7"


def test_mqtt_wire_protocol_and_device_identifiers_are_intentionally_unchanged():
    from custom_components.hal_gaming_control.const import DOMAIN, ROOT as MQTT_ROOT
    from custom_components.hal_gaming_control.entity import GamingEntity
    from custom_components.hal_gaming_control.legacy_activity_cleanup import exact_legacy_topics
    from types import SimpleNamespace

    assert DOMAIN == "hal_gaming_control"
    assert MQTT_ROOT == "SmartHouse/Gaming"
    coordinator = SimpleNamespace(
        device_id="pc1", entry=SimpleNamespace(data={"name": "Child PC"}),
        async_add_listener=lambda callback: lambda: None)
    entity = GamingEntity(coordinator, "gaming_restriction", "Gaming restriction")
    assert entity.unique_id == "pc1_gaming_restriction"
    assert entity.device_info["identifiers"] == {("mqtt", "smarthouse_gaming_pc1")}
    assert any("smarthouse_gaming_pc1" in topic
               for topic in exact_legacy_topics("pc1"))


def test_fresh_hal_gaming_control_config_entry_and_stable_unique_id(hass):
    from custom_components.hal_gaming_control.const import DOMAIN
    entry = MockConfigEntry(domain=DOMAIN, unique_id="pc1", title="Child PC",
                            data={"device_id": "pc1", "name": "Child PC",
                                  "protocol_version": 1, "games": [],
                                  "actions": ["terminate_game", "lock_pc"]},
                            options={"enabled": True, "daily": 120,
                                     "tracked_apps": [{"process": "RobloxPlayerBeta.exe",
                                                       "signature": None, "name": "Roblox"}]})
    entry.add_to_hass(hass)
    assert hass.config_entries.async_entries("hal_gaming_control") == [entry]
    assert hass.config_entries.async_entries("smarthouse_gaming") == []
    assert hass.config_entries.async_entries("parental") == []
    assert hass.config_entries.async_entries("parental_control") == []
    reg = er.async_get(hass)
    record = reg.async_get_or_create("sensor", DOMAIN, "pc1_active_game", config_entry=entry)
    assert record.platform == DOMAIN and record.unique_id == "pc1_active_game"
    assert entry.options["tracked_apps"][0]["name"] == "Roblox"
