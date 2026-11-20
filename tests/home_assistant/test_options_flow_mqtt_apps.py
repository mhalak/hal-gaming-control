"""Options Flow stage 1 (#52): read-only broker information and read-only Tracked applications.

Every test drives the real Home Assistant options flow manager.
"""
import json
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming import config_flow as cf
from custom_components.smarthouse_gaming.const import DOMAIN

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

PACKAGE = Path(cf.__file__).parent
SECRETS = {"username": "broker_user_x", "password": "S3cretPassw0rd!", "certificate": "/config/secret-ca.pem",
           "client_cert": "/config/secret-client.pem", "client_key": "/config/secret-client.key"}
DATA1 = {"device_id": "pc1", "name": "Gaming PC 1", "protocol_version": 1,
         "games": ["Minecraft", "Roblox"], "actions": ["terminate_game", "lock_pc"]}
DATA2 = {"device_id": "pc2", "name": "Gaming PC 2", "protocol_version": 1,
         "games": ["Fortnite"], "actions": ["lock_pc"]}
NOT_AVAILABLE = "not available"


@pytest.fixture
def expected_lingering_timers():
    return True


@contextmanager
def brokers(hass, datas):
    """Present MQTT config entries to the flow without setting up a real MQTT client (sockets are blocked in CI).
    None leaves the real registry untouched."""
    if datas is None:
        yield
        return
    real = hass.config_entries.async_entries
    fakes = [SimpleNamespace(domain="mqtt", data=MappingProxyType(dict(d))) for d in datas]

    def fake(domain=None, *args, **kwargs):
        return list(fakes) if domain == "mqtt" else real(domain, *args, **kwargs)

    with patch.object(hass.config_entries, "async_entries", side_effect=fake):
        yield


def broker(**extra):
    return {"broker": "mqtt.home.lan", "port": 8883} | extra


def add_device(hass, data=DATA1, options=None):
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id=data["device_id"], options=options or {"daily": 60})
    entry.add_to_hass(hass)
    return entry


async def open_step(hass, entry, step, connected=True, direct=False, mqtt_entries=None):
    """Open one options step. MQTT entries are presented only while the step runs: HA itself also lists
    entries by domain when it loads dependencies, and must never see these stand-ins."""
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    with brokers(hass, mqtt_entries), patch.object(cf.mqtt, "is_connected", return_value=connected), \
            patch.object(cf, "direct_mode", return_value=direct):
        return manager, await manager.async_configure(result["flow_id"], {"next_step_id": step})


def flat(result):
    return json.dumps(result, default=str)


async def test_menu_adds_tracked_applications_and_keeps_existing_items(hass, enable_custom_integrations):
    entry = add_device(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    options = result["menu_options"]
    assert options["tracked_apps"] == "Tracked applications"
    for key in ("limits", "mqtt_settings", "update_settings", "save"):
        assert key in options
    assert list(options).index("tracked_apps") < list(options).index("save")


async def test_mqtt_step_shows_status_and_non_secret_broker_data(hass, enable_custom_integrations):
    entry = add_device(hass)
    _, result = await open_step(hass, entry, "mqtt_settings", connected=True, direct=True,
                                mqtt_entries=[broker(certificate="auto")])
    placeholders = result["description_placeholders"]
    assert placeholders == {
        "connection": "Connected", "device_id": "pc1", "root": "SmartHouse/Gaming/pc1",
        "mode": "Scoped discovery", "broker_host": "mqtt.home.lan", "broker_port": "8883",
        "broker_tls": "Yes", "connection_help": placeholders["connection_help"]}
    assert placeholders["connection_help"]


@pytest.mark.parametrize("extra, tls", [({}, "No"), ({"certificate": "auto"}, "Yes"),
                                        ({"certificate": "/config/ca.pem"}, "Yes")])
async def test_tls_flag_is_yes_no_only(hass, enable_custom_integrations, extra, tls):
    entry = add_device(hass)
    _, result = await open_step(hass, entry, "mqtt_settings", mqtt_entries=[broker(**extra)])
    assert result["description_placeholders"]["broker_tls"] == tls
    assert "ca.pem" not in flat(result)


async def test_no_secret_in_result_or_logs(hass, enable_custom_integrations, caplog):
    entry = add_device(hass)
    caplog.set_level(logging.DEBUG)
    manager, result = await open_step(hass, entry, "mqtt_settings", connected=False, mqtt_entries=[broker(**SECRETS)])
    down = flat(result)
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    _, shown = await open_step(hass, entry, "mqtt_settings", mqtt_entries=[broker(**SECRETS)])
    assert shown["description_placeholders"]["broker_host"] == "mqtt.home.lan"
    for secret in SECRETS.values():
        assert secret not in flat(shown)
        assert secret not in down
        assert secret not in caplog.text
        assert secret not in json.dumps(dict(entry.options)) + json.dumps(dict(entry.data))


@pytest.mark.parametrize("broker_data", [
    {"port": 1883},
    {"broker": "", "port": 1883},
    {"broker": 5, "port": 1883},
    {"broker": "host", "port": "abc"},
    {"broker": "host", "port": 0},
    {"broker": "host", "port": 70000},
    {"broker": "host", "port": True},
    {"broker": "x" * 300, "port": 1883},
    {"broker": "bad\nhost", "port": 1883},
])
async def test_unreadable_broker_data_is_not_available(hass, enable_custom_integrations, broker_data):
    entry = add_device(hass)
    _, result = await open_step(hass, entry, "mqtt_settings", mqtt_entries=[broker_data])
    placeholders = result["description_placeholders"]
    assert placeholders["broker_host"] == NOT_AVAILABLE
    assert placeholders["broker_port"] == NOT_AVAILABLE
    assert placeholders["broker_tls"] == NOT_AVAILABLE
    assert placeholders["device_id"] == "pc1"


@pytest.mark.parametrize("datas", [(), (broker(), broker())])
async def test_missing_or_ambiguous_mqtt_entries_are_not_guessed(hass, enable_custom_integrations, datas):
    entry = add_device(hass)
    _, result = await open_step(hass, entry, "mqtt_settings", mqtt_entries=list(datas))
    assert result["description_placeholders"]["broker_host"] == NOT_AVAILABLE
    assert result["description_placeholders"]["broker_port"] == NOT_AVAILABLE


@pytest.fixture
def mqtt_config_entry_data():
    return broker(**SECRETS) | {"broker": "real-broker.lan", "port": 1884}


async def test_real_mqtt_config_entry_is_read(hass, enable_custom_integrations, mqtt_mock):
    """Against the real HA MQTT config entry created by the HA test harness, secrets included."""
    entry = add_device(hass)
    assert hass.config_entries.async_entries("mqtt")[0].data["password"] == SECRETS["password"]
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "mqtt_settings"})
    placeholders = result["description_placeholders"]
    assert (placeholders["broker_host"], placeholders["broker_port"], placeholders["broker_tls"]) == (
        "real-broker.lan", "1884", "Yes")
    for secret in SECRETS.values():
        assert secret not in flat(result)


async def test_disconnected_branch_gives_one_actionable_hint_without_secrets(hass, enable_custom_integrations):
    entry = add_device(hass)
    _, down = await open_step(hass, entry, "mqtt_settings", connected=False, mqtt_entries=[broker(**SECRETS)])
    _, up = await open_step(hass, entry, "mqtt_settings", connected=True, mqtt_entries=[broker(**SECRETS)])
    assert down["description_placeholders"]["connection"] == "Disconnected"
    hint = down["description_placeholders"]["connection_help"]
    assert "Settings → Devices & services → MQTT" in hint
    assert hint != up["description_placeholders"]["connection_help"]
    assert "\n" not in hint
    for secret in SECRETS.values():
        assert secret not in hint


async def test_mqtt_step_never_starts_broker_flow_or_writes(hass, enable_custom_integrations):
    entry = add_device(hass)
    with patch.object(hass.config_entries.flow, "async_init", AsyncMock()) as init, \
            patch.object(hass.config_entries, "async_update_entry") as update:
        manager, result = await open_step(hass, entry, "mqtt_settings", mqtt_entries=[broker()])
        await manager.async_configure(result["flow_id"], {})
    init.assert_not_called()
    update.assert_not_called()
    assert not result["data_schema"].schema
    assert hass.config_entries.flow.async_progress() == []


def description_texts(step):
    for rel in ("strings.json", "translations/en.json"):
        yield json.loads((PACKAGE / rel).read_text())["options"]["step"][step]


def test_mqtt_text_separates_broker_and_windows_agent_and_navigates_by_path():
    for step in description_texts("mqtt_settings"):
        text = step["description"]
        assert "shared Home Assistant MQTT broker" in text
        assert "Windows agent" in text
        assert "does not change the other" in text
        assert "Settings → Devices & services → MQTT" in text
        assert "http" not in text.lower() and "/config/" not in text
        for token in ("{broker_host}", "{broker_port}", "{broker_tls}", "{connection_help}", "{connection}"):
            assert token in text


def test_mqtt_text_placeholders_are_all_supplied():
    supplied = {"connection", "device_id", "root", "mode", "broker_host", "broker_port", "broker_tls", "connection_help"}
    for step in description_texts("mqtt_settings"):
        assert set(re.findall(r"{(\w+)}", step["description"])) <= supplied


def test_tracked_apps_text_is_read_only_and_points_to_issue_7():
    for step in description_texts("tracked_apps"):
        assert step["title"] == "Tracked applications"
        text = step["description"]
        assert "{device}" in text and "{apps}" in text
        assert "read-only" in text.lower()
        assert "#7" in text and "not available yet" in text
        assert set(re.findall(r"{(\w+)}", text)) <= {"device", "apps", "count"}


async def test_tracked_apps_lists_current_applications(hass, enable_custom_integrations):
    entry = add_device(hass)
    _, result = await open_step(hass, entry, "tracked_apps")
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "tracked_apps"
    placeholders = result["description_placeholders"]
    assert placeholders["device"] == "Gaming PC 1"
    assert placeholders["count"] == "2"
    assert placeholders["apps"] == "• Minecraft\n• Roblox"
    assert not result["data_schema"].schema


@pytest.mark.parametrize("data", [DATA1 | {"games": []}, {k: v for k, v in DATA1.items() if k != "games"}])
async def test_tracked_apps_empty_list_has_clear_message(hass, enable_custom_integrations, data):
    entry = add_device(hass, data)
    _, result = await open_step(hass, entry, "tracked_apps")
    placeholders = result["description_placeholders"]
    assert placeholders["count"] == "0"
    assert placeholders["apps"] == "No applications are tracked for this computer yet."


async def test_tracked_apps_isolated_per_device(hass, enable_custom_integrations):
    first, second = add_device(hass, DATA1), add_device(hass, DATA2)
    _, one = await open_step(hass, first, "tracked_apps")
    _, two = await open_step(hass, second, "tracked_apps")
    assert one["description_placeholders"]["device"] == "Gaming PC 1"
    assert "Fortnite" not in one["description_placeholders"]["apps"]
    assert two["description_placeholders"]["device"] == "Gaming PC 2"
    assert two["description_placeholders"]["apps"] == "• Fortnite"
    assert "Minecraft" not in flat(two)


async def test_tracked_apps_back_returns_to_menu_without_writes(hass, enable_custom_integrations):
    entry = add_device(hass, options={"daily": 60, "per_game": {"Roblox": 30}})
    before = (dict(entry.options), dict(entry.data))
    with patch.object(hass.config_entries, "async_update_entry") as update:
        manager, result = await open_step(hass, entry, "tracked_apps")
        result = await manager.async_configure(result["flow_id"], {})
    update.assert_not_called()
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "menu"
    assert (dict(entry.options), dict(entry.data)) == before


async def test_new_steps_do_not_change_saved_options(hass, enable_custom_integrations):
    options = {"daily": 60, "weekly": 300, "weekend_daily": 120, "unlimited": True, "per_game": {"Roblox": 30},
               "actions": ["lock_pc"], "bonus_minutes": 30, "bonus_date": "2026-11-20"}
    plain = add_device(hass, DATA1, dict(options))
    visited = add_device(hass, DATA2, dict(options))
    manager = hass.config_entries.options
    result = await manager.async_init(plain.entry_id)
    await manager.async_configure(result["flow_id"], {"next_step_id": "save"})
    manager, result = await open_step(hass, visited, "tracked_apps")
    result = await manager.async_configure(result["flow_id"], {})
    with patch.object(cf.mqtt, "is_connected", return_value=True):
        result = await manager.async_configure(result["flow_id"], {"next_step_id": "mqtt_settings"})
        result = await manager.async_configure(result["flow_id"], {})
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "save"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    for key in ("per_game", "actions", "daily", "weekly", "weekend_daily", "unlimited", "bonus_minutes", "bonus_date"):
        assert visited.options[key] == plain.options[key]
    assert visited.options == plain.options
    assert visited.options["per_game"] == {"Roblox": 30}
    assert visited.options["actions"] == ["lock_pc"]
