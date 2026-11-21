"""HA-owned Tracked applications and safe MQTT connection guidance."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming import config_flow as cf
from custom_components.smarthouse_gaming.const import DOMAIN

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

DATA1 = {"device_id": "pc1", "name": "Gaming PC 1", "protocol_version": 1,
         "games": ["Minecraft", "Roblox"], "actions": ["terminate_game", "lock_pc"]}
DATA2 = {"device_id": "pc2", "name": "Gaming PC 2", "protocol_version": 1,
         "games": ["Fortnite"], "actions": ["lock_pc"]}
PACKAGE = Path(cf.__file__).parent


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


def add_device(hass, data, options=None):
    entry = MockConfigEntry(domain=DOMAIN, title=data["name"], data=data,
                            unique_id=data["device_id"], options=options or {})
    entry.add_to_hass(hass)
    return entry


async def open_step(hass, entry, step):
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    if step == "tracked_apps":
        with patch.object(cf, "_discover_foreground_candidate", new=AsyncMock(return_value=None)):
            result = await manager.async_configure(result["flow_id"], {"next_step_id": step})
    else:
        result = await manager.async_configure(result["flow_id"], {"next_step_id": step})
    return manager, result


async def test_menu_adds_tracked_apps_without_removing_existing_navigation(
        hass, enable_custom_integrations):
    result = await hass.config_entries.options.async_init(add_device(hass, DATA1).entry_id)
    assert set(result["menu_options"]) == {
        "limits", "mqtt_settings", "tracked_apps", "update_settings", "save"}


async def test_tracked_apps_are_isolated_per_device(hass, enable_custom_integrations):
    first, second = add_device(hass, DATA1), add_device(hass, DATA2)
    _, one = await open_step(hass, first, "tracked_apps")
    _, two = await open_step(hass, second, "tracked_apps")
    assert one["description_placeholders"] == {
        "device": "Gaming PC 1", "count": "0",
        "apps": "No HA-managed applications configured yet.",
        "legacy_apps": "• Minecraft\n• Roblox",
        "candidate": "No fresh foreground application detected"}
    assert two["description_placeholders"] == {
        "device": "Gaming PC 2", "count": "0",
        "apps": "No HA-managed applications configured yet.",
        "legacy_apps": "• Fortnite",
        "candidate": "No fresh foreground application detected"}
    assert "Fortnite" not in json.dumps(one, default=str)
    assert "Minecraft" not in json.dumps(two, default=str)
    assert one["type"] == two["type"] == data_entry_flow.FlowResultType.MENU
    assert set(one["menu_options"]) == {"add_app", "rename_app", "remove_app", "menu"}


@pytest.mark.parametrize("data", [DATA1 | {"games": []}, {k: v for k, v in DATA1.items() if k != "games"}])
async def test_tracked_apps_empty_state_is_explicit(hass, enable_custom_integrations, data):
    _, result = await open_step(hass, add_device(hass, data), "tracked_apps")
    assert result["description_placeholders"]["count"] == "0"
    assert result["description_placeholders"]["apps"] == (
        "No HA-managed applications configured yet.")


async def test_tracked_apps_back_navigation_is_read_only(hass, enable_custom_integrations):
    options = {"daily": 60, "weekly": 300, "per_game": {"Roblox": 30},
               "actions": ["lock_pc"]}
    entry = add_device(hass, DATA1, options)
    before = (dict(entry.data), dict(entry.options))
    with patch.object(hass.config_entries, "async_update_entry") as update:
        manager, result = await open_step(hass, entry, "tracked_apps")
        result = await manager.async_configure(result["flow_id"], {"next_step_id": "menu"})
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "menu"
    update.assert_not_called()
    assert (dict(entry.data), dict(entry.options)) == before


async def test_visiting_tracked_apps_preserves_existing_settings_on_save(
        hass, enable_custom_integrations):
    options = {"daily": 60, "weekly": 300, "weekend_daily": 120,
               "unlimited": True, "per_game": {"Roblox": 30},
               "actions": ["lock_pc"], "bonus_minutes": 30,
               "bonus_date": "2026-11-20"}
    entry = add_device(hass, DATA1, options)
    manager, result = await open_step(hass, entry, "tracked_apps")
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "menu"})
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "save"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    for key, value in options.items():
        assert entry.options[key] == value


@pytest.mark.parametrize("certificate, expected", [(None, "No"), ("auto", "Yes"), ("/secret/ca.pem", "Yes")])
async def test_mqtt_step_reports_tls_without_exposing_certificate(
        hass, enable_custom_integrations, certificate, expected):
    entry = add_device(hass, DATA1)
    mqtt_entry = SimpleNamespace(data={"broker": "mqtt.home.lan", "port": 8883,
                                       "certificate": certificate,
                                       "username": "private-user", "password": "private-password"},
                                 options={})
    real_entries = hass.config_entries.async_entries

    def entries(domain=None, *args, **kwargs):
        return [mqtt_entry] if domain == "mqtt" else real_entries(domain, *args, **kwargs)

    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    with patch.object(hass.config_entries, "async_entries", side_effect=entries), \
            patch.object(cf.mqtt, "is_connected", return_value=True):
        result = await manager.async_configure(result["flow_id"], {"next_step_id": "mqtt_settings"})
    placeholders = result["description_placeholders"]
    assert placeholders["tls"] == expected
    rendered = json.dumps(result, default=str)
    assert "private-user" not in rendered and "private-password" not in rendered
    assert "ca.pem" not in rendered


async def test_disconnected_mqtt_step_has_safe_navigation_hint(hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    with patch.object(cf.mqtt, "is_connected", return_value=False):
        _, result = await open_step(hass, entry, "mqtt_settings")
    hint = result["description_placeholders"]["connection_help"]
    assert "Settings → Devices & services → MQTT" in hint
    assert "log" in hint.lower()
    assert "http" not in hint.lower()


async def test_strings_describe_read_only_apps_and_separate_connections():
    for relative in ("strings.json", "translations/en.json"):
        steps = json.loads((PACKAGE / relative).read_text())["options"]["step"]
        tracked = steps["tracked_apps"]["description"]
        mqtt_text = steps["mqtt_settings"]["description"]
        assert "HA-managed" in tracked and "{candidate}" in tracked
        assert "nothing is written to Windows" in tracked
        assert "shared" in mqtt_text.lower() and "Windows agent" in mqtt_text
        assert "does not change" in mqtt_text
        assert "{tls}" in mqtt_text and "{connection_help}" in mqtt_text


async def test_live_foreground_candidate_is_scoped_and_advisory(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    topic = "SmartHouse/Gaming/pc1/state/foreground_candidate"
    current = cf.dt_util.utcnow().timestamp()
    value = {"version": 1, "device_id": "pc1", "process": "chrome.exe",
             "token": "a" * 32, "signature": None, "observed_at": current}
    calls = []

    async def subscribe(_hass, requested, callback, qos=0):
        calls.append((requested, qos))
        callback(SimpleNamespace(topic=topic, payload=json.dumps(value | {"device_id": "pc2"}),
                                 retain=False))
        callback(SimpleNamespace(topic=topic, payload=json.dumps(value), retain=True))
        callback(SimpleNamespace(topic=topic, payload=json.dumps(value), retain=False))
        return lambda: calls.append(("unsubscribed", 0))

    with patch.object(cf.mqtt, "async_subscribe", side_effect=subscribe), \
            patch.object(cf, "_listen_window", new=AsyncMock()):
        result = await manager.async_configure(result["flow_id"], {"next_step_id": "tracked_apps"})

    assert result["description_placeholders"]["candidate"] == "chrome.exe"
    assert "chrome.exe" not in result["description_placeholders"]["apps"]
    assert calls == [(topic, 0), ("unsubscribed", 0)]
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert entry.data["games"] == DATA1["games"]


async def test_generic_runtime_detected_but_marked_not_enrollable(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value={"process": "javaw.exe",
                                                   "token": "b" * 32,
                                                   "observed_at": 100})):
        manager = hass.config_entries.options
        result = await manager.async_init(entry.entry_id)
        result = await manager.async_configure(result["flow_id"], {"next_step_id": "tracked_apps"})
    assert "ambiguous Java runtime" in result["description_placeholders"]["candidate"]


CANDIDATE = {
    "process": "javaw.exe",
    "signature": {"kind": "java_class", "value": "net.minecraft.client.main.Main"},
    "token": "a" * 32,
    "observed_at": 100,
}


async def test_ha_only_add_app_persists_mapping_and_preserves_budgets(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"daily": 90, "per_game": {"Roblox": 40},
                                    "unlimited": True, "bonus_minutes": 20})
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=CANDIDATE)) as observe, \
            patch.object(cf.mqtt, "async_publish", new=AsyncMock()) as publish:
        manager = hass.config_entries.options
        view = await manager.async_init(entry.entry_id)
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "tracked_apps"})
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "add_app"})
        assert view["step_id"] == "add_app"
        assert "net.minecraft.client.main.Main" in view["description_placeholders"]["candidate"]
        result = await manager.async_configure(view["flow_id"], {"name": "Minecraft Java"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["tracked_apps"] == [
        {"process": "javaw.exe", "signature": CANDIDATE["signature"],
         "name": "Minecraft Java"}]
    for key in ("daily", "per_game", "unlimited", "bonus_minutes"):
        assert result["data"][key] == entry.options[key]
    assert observe.await_count == 3
    publish.assert_not_called()
    assert entry.data == DATA1


async def test_stale_or_changed_foreground_does_not_enroll(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    stale = CANDIDATE | {"token": "b" * 32}
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(side_effect=[CANDIDATE, CANDIDATE, stale])):
        manager = hass.config_entries.options
        view = await manager.async_init(entry.entry_id)
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "tracked_apps"})
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "add_app"})
        result = await manager.async_configure(view["flow_id"], {"name": "Minecraft"})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "candidate_changed"
    assert "tracked_apps" not in entry.options


async def test_duplicate_app_is_rejected_without_overwriting(
        hass, enable_custom_integrations):
    existing = [{"process": "javaw.exe", "signature": CANDIDATE["signature"],
                 "name": "Original"}]
    entry = add_device(hass, DATA1, {"tracked_apps": existing})
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=CANDIDATE)):
        manager = hass.config_entries.options
        view = await manager.async_init(entry.entry_id)
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "tracked_apps"})
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "add_app"})
        result = await manager.async_configure(view["flow_id"], {"name": "Duplicated"})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_application"
    assert entry.options["tracked_apps"] == existing


async def test_rename_app_keeps_identity_and_other_options(
        hass, enable_custom_integrations):
    existing = [{"process": "javaw.exe", "signature": CANDIDATE["signature"],
                 "name": "Minecraft"}]
    entry = add_device(hass, DATA1, {"tracked_apps": existing, "weekly": 240})
    from custom_components.smarthouse_gaming.app_registry import identity_key
    key = identity_key("javaw.exe", CANDIDATE["signature"])
    manager = hass.config_entries.options
    manager, view = await open_step(hass, entry, "tracked_apps")
    view = await manager.async_configure(view["flow_id"], {"next_step_id": "rename_app"})
    result = await manager.async_configure(
        view["flow_id"], {"target": key, "name": "Minecraft Java"})
    assert result["data"]["tracked_apps"] == [
        existing[0] | {"name": "Minecraft Java"}]
    assert result["data"]["weekly"] == 240
    assert entry.data == DATA1


async def test_remove_app_only_affects_selected_device(
        hass, enable_custom_integrations):
    existing = [{"process": "javaw.exe", "signature": CANDIDATE["signature"],
                 "name": "Minecraft"}]
    first = add_device(hass, DATA1, {"tracked_apps": existing, "daily": 20})
    second = add_device(hass, DATA2, {"tracked_apps": existing, "daily": 40})
    from custom_components.smarthouse_gaming.app_registry import identity_key
    key = identity_key("javaw.exe", CANDIDATE["signature"])
    manager = hass.config_entries.options
    manager, view = await open_step(hass, first, "tracked_apps")
    view = await manager.async_configure(view["flow_id"], {"next_step_id": "remove_app"})
    result = await manager.async_configure(view["flow_id"], {"target": key})
    assert result["data"]["tracked_apps"] == []
    assert result["data"]["daily"] == 20
    assert second.options == {"tracked_apps": existing, "daily": 40}


async def test_concurrent_app_changes_not_overwritten_but_other_options_preserved(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"weekly": 120})
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=CANDIDATE)):
        manager = hass.config_entries.options
        view = await manager.async_init(entry.entry_id)
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "tracked_apps"})
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "add_app"})
        hass.config_entries.async_update_entry(entry, options={
            "weekly": 240, "tracked_apps": [{"process": "chrome.exe",
                                               "signature": None, "name": "Chrome"}]})
        result = await manager.async_configure(view["flow_id"], {"name": "Minecraft"})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "configuration_changed"
    assert entry.options["weekly"] == 240


async def test_ambiguous_java_cannot_be_enrolled(
        hass, enable_custom_integrations):
    vague = CANDIDATE | {"signature": None}
    entry = add_device(hass, DATA1)
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=vague)):
        manager = hass.config_entries.options
        view = await manager.async_init(entry.entry_id)
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "tracked_apps"})
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "add_app"})
    assert view["type"] == data_entry_flow.FlowResultType.FORM
    assert view["errors"]["base"] == "no_live_candidate"
    assert not view["data_schema"].schema


async def test_unrelated_options_save_preserves_app_mapping_added_concurrently(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"daily": 100})
    manager = hass.config_entries.options
    view = await manager.async_init(entry.entry_id)
    latest = {
        "daily": 90,
        "tracked_apps": [
            {"process": "javaw.exe", "signature": CANDIDATE["signature"],
             "name": "Minecraft Java"}],
    }
    hass.config_entries.async_update_entry(entry, options=latest)
    result = await manager.async_configure(view["flow_id"], {"next_step_id": "save"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["tracked_apps"] == latest["tracked_apps"]
    assert result["data"]["daily"] == 90


@pytest.mark.parametrize("initial", [None, CANDIDATE | {"signature": None}])
async def test_empty_candidate_form_can_retry_without_enrolling(
        hass, enable_custom_integrations, initial):
    entry = add_device(hass, DATA1)
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(side_effect=[initial, initial, initial, CANDIDATE, CANDIDATE])):
        manager = hass.config_entries.options
        view = await manager.async_init(entry.entry_id)
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "tracked_apps"})
        view = await manager.async_configure(view["flow_id"], {"next_step_id": "add_app"})
        assert view["errors"]["base"] == "no_live_candidate"
        view = await manager.async_configure(view["flow_id"], {})
        assert view["errors"]["base"] == "no_live_candidate"
        assert "tracked_apps" not in entry.options
        view = await manager.async_configure(view["flow_id"], {})
        assert view["type"] == data_entry_flow.FlowResultType.FORM
        assert "net.minecraft.client.main.Main" in view["description_placeholders"]["candidate"]
        assert "tracked_apps" not in entry.options
        result = await manager.async_configure(view["flow_id"], {"name": "Minecraft"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["tracked_apps"][0]["name"] == "Minecraft"
