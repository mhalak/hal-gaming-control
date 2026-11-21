"""One-screen tracked apps editor and safe HA/MQTT options flow."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming import config_flow as cf
from custom_components.smarthouse_gaming.app_editor import raw_label
from custom_components.smarthouse_gaming.const import DOMAIN

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

DATA1 = {"device_id": "pc1", "name": "Gaming PC 1", "protocol_version": 1,
         "games": ["Minecraft", "Roblox"], "actions": ["terminate_game", "lock_pc"]}
DATA2 = {"device_id": "pc2", "name": "Gaming PC 2", "protocol_version": 1,
         "games": ["Fortnite"], "actions": ["lock_pc"]}
PACKAGE = Path(cf.__file__).parent
MINECRAFT = {"process": "javaw.exe", "signature": {
    "kind": "java_class", "value": "net.minecraft.client.main.Main"},
    "token": "a" * 32, "observed_at": 100}
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None,
          "token": "b" * 32, "observed_at": 100}


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


def add_device(hass, data, options=None):
    entry = MockConfigEntry(domain=DOMAIN, title=data["name"], data=data,
                            unique_id=data["device_id"], options=options or {})
    entry.add_to_hass(hass)
    return entry


async def open_step(hass, entry, step, candidate=None):
    manager = hass.config_entries.options
    view = await manager.async_init(entry.entry_id)
    if step == "tracked_apps":
        with patch.object(cf, "_discover_foreground_candidate",
                          new=AsyncMock(return_value=candidate)):
            view = await manager.async_configure(
                view["flow_id"], {"next_step_id": step})
    else:
        view = await manager.async_configure(
            view["flow_id"], {"next_step_id": step})
    return manager, view


def rows(view):
    field = next(k for k in view["data_schema"].schema if str(k) == "applications")
    return field.default()


async def test_menu_exposes_only_live_settings_without_mutating_saved_options(
        hass, enable_custom_integrations):
    saved = {"daily": 90, "schedule_enabled": True,
             "schedule_start": "16:00", "schedule_end": "20:00",
             "update_catalog_url": "https://example.com/catalog.json",
             "actions": ["lock_pc"]}
    entry = add_device(hass, DATA1, saved)
    view = await hass.config_entries.options.async_init(entry.entry_id)
    assert view["type"] == data_entry_flow.FlowResultType.MENU
    assert view["menu_options"] == ["mqtt_settings", "tracked_apps"]
    assert entry.options == saved


async def test_one_form_shows_existing_name_and_raw_process(
        hass, enable_custom_integrations):
    old = [{"process": "javaw.exe", "signature": MINECRAFT["signature"],
            "name": "Minecraft Java"}]
    entry = add_device(hass, DATA1, {"tracked_apps": old, "daily": 90})
    manager, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    assert view["type"] == data_entry_flow.FlowResultType.FORM
    assert view["step_id"] == "tracked_apps"
    assert "RobloxPlayerBeta.exe" in view["description_placeholders"]["candidate"]
    assert rows(view) == [{
        "name": "Minecraft Java",
        "detected": "javaw.exe — java_class: net.minecraft.client.main.Main"}]
    # One structured selector, not separate Add/Remove/Rename navigation.
    schema = list(view["data_schema"].schema.values())
    assert len(schema) == 1
    assert schema[0].config["multiple"] is True
    assert schema[0].config["label_field"] == "name"
    assert schema[0].config["description_field"] == "detected"
    fields = schema[0].config["fields"]
    assert fields["detected"]["default"] == "RobloxPlayerBeta.exe"
    assert all(step not in view for step in ("add_app", "rename_app", "remove_app"))
    assert manager


async def test_no_candidate_shows_clear_preview_and_does_not_import_windows_rules(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    _, view = await open_step(hass, entry, "tracked_apps")
    assert rows(view) == []
    assert "No fresh foreground" in view["description_placeholders"]["candidate"]
    assert "tracked_apps" not in entry.options
    assert "Minecraft" not in json.dumps(view, default=str)


async def test_add_detected_game_once_in_same_form_preserves_limits(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"daily": 90, "per_game": {"Roblox": 40},
                                    "unlimited": True})
    manager, view = await open_step(hass, entry, "tracked_apps", MINECRAFT)
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=MINECRAFT)) as probe, \
            patch.object(cf.mqtt, "async_publish",
                         new=AsyncMock()) as publish:
        result = await manager.async_configure(view["flow_id"], {
            "applications": [{"name": "Minecraft", "detected": raw_label(MINECRAFT)}]})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["tracked_apps"] == [{
        "process": "javaw.exe", "signature": MINECRAFT["signature"], "name": "Minecraft"}]
    for key in ("daily", "per_game", "unlimited"):
        assert result["data"][key] == entry.options[key]
    assert entry.data == DATA1
    assert probe.await_count == 1
    publish.assert_not_called()


async def test_rename_remove_and_add_combined_in_one_submit(
        hass, enable_custom_integrations):
    old = [{"process": "javaw.exe", "signature": MINECRAFT["signature"],
            "name": "Old Minecraft"},
           {"process": "chrome.exe", "signature": None, "name": "Chrome test"}]
    entry = add_device(hass, DATA1, {"tracked_apps": old, "weekly": 120})
    manager, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    assert len(rows(view)) == 2
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=ROBLOX)):
        result = await manager.async_configure(view["flow_id"], {
            "applications": [
                {"name": "Minecraft Java", "detected": raw_label(MINECRAFT)},
                {"name": "Roblox", "detected": raw_label(ROBLOX)},
            ]})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["weekly"] == 120
    assert result["data"]["tracked_apps"] == [
        old[0] | {"name": "Minecraft Java"},
        {"process": ROBLOX["process"], "signature": None, "name": "Roblox"}]


async def test_rename_or_delete_existing_works_without_live_game(
        hass, enable_custom_integrations):
    old = [{"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}]
    entry = add_device(hass, DATA1, {"tracked_apps": old})
    manager, view = await open_step(hass, entry, "tracked_apps")
    result = await manager.async_configure(view["flow_id"], {"applications": [
        {"name": "Roblox New", "detected": "RobloxPlayerBeta.exe"}]})
    assert result["data"]["tracked_apps"][0]["name"] == "Roblox New"
    # In a subsequent flow delete the last row via the built-in remove icon.
    entry2 = add_device(hass, DATA2, {"tracked_apps": old})
    manager, view = await open_step(hass, entry2, "tracked_apps")
    result = await manager.async_configure(view["flow_id"], {"applications": []})
    assert result["data"]["tracked_apps"] == []
    assert entry.options["tracked_apps"][0]["name"] == "Roblox New"
    assert entry2.options["tracked_apps"] == []


@pytest.mark.parametrize("changed", [
    MINECRAFT | {"token": "b" * 32},
    ROBLOX,
    None,
])
async def test_new_candidate_changed_cannot_enroll(
        hass, enable_custom_integrations, changed):
    entry = add_device(hass, DATA1)
    manager, view = await open_step(hass, entry, "tracked_apps", MINECRAFT)
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=changed)):
        result = await manager.async_configure(view["flow_id"], {"applications": [
            {"name": "Minecraft", "detected": raw_label(MINECRAFT)}]})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "candidate_changed"
    assert "tracked_apps" not in entry.options


async def test_forged_new_process_or_duplicate_is_rejected(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    manager, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    # HA's native SelectSelector rejects forged choices BEFORE our callback.
    with pytest.raises(data_entry_flow.InvalidData):
        await manager.async_configure(view["flow_id"], {"applications": [
            {"name": "Other", "detected": "private.exe"}]})
    assert "tracked_apps" not in entry.options

    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=ROBLOX)):
        result = await manager.async_configure(view["flow_id"], {
            "applications": [
                {"name": "Roblox", "detected": "RobloxPlayerBeta.exe"},
                {"name": "Duplicate", "detected": "RobloxPlayerBeta.exe"}]})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_application"


async def test_concurrent_mappings_cannot_be_overwritten(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"daily": 90})
    manager, view = await open_step(hass, entry, "tracked_apps", MINECRAFT)
    hass.config_entries.async_update_entry(entry, options={
        "daily": 75, "tracked_apps": [
            {"process": "chrome.exe", "signature": None, "name": "Chrome"}]})
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=MINECRAFT)):
        result = await manager.async_configure(view["flow_id"], {"applications": [
            {"name": "Minecraft", "detected": raw_label(MINECRAFT)}]})
    assert result["errors"]["base"] == "configuration_changed"
    assert entry.options["daily"] == 75
    assert entry.options["tracked_apps"][0]["name"] == "Chrome"


async def test_ambiguous_bare_java_is_shown_but_cannot_be_enrolled(
        hass, enable_custom_integrations):
    vague = MINECRAFT | {"signature": None}
    entry = add_device(hass, DATA1)
    manager, view = await open_step(hass, entry, "tracked_apps", vague)
    assert "ambiguous" in view["description_placeholders"]["candidate"]
    # Ambiguous Java isn't an available dropdown option.
    with pytest.raises(data_entry_flow.InvalidData):
        await manager.async_configure(view["flow_id"], {"applications": [
            {"name": "Minecraft", "detected": "javaw.exe"}]})
    assert "tracked_apps" not in entry.options


async def test_foreground_candidate_rejects_foreign_and_retained_mqtt(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    topic = "SmartHouse/Gaming/pc1/state/foreground_candidate"
    current = cf.dt_util.utcnow().timestamp()
    sample = {"version": 1, "device_id": "pc1", "process": "chrome.exe",
              "token": "a" * 32, "signature": None, "observed_at": current}
    calls = []

    async def subscribe(_hass, requested, cb, qos=0):
        calls.append((requested, qos))
        cb(SimpleNamespace(topic=topic, payload=json.dumps(sample | {
            "device_id": "pc2"}), retain=False))
        cb(SimpleNamespace(topic=topic, payload=json.dumps(sample), retain=True))
        cb(SimpleNamespace(topic=topic, payload=json.dumps(sample), retain=False))
        return lambda: calls.append(("unsubscribed", 0))

    manager = hass.config_entries.options
    view = await manager.async_init(entry.entry_id)
    with patch.object(cf.mqtt, "async_subscribe", side_effect=subscribe), \
            patch.object(cf, "_listen_window", new=AsyncMock()):
        view = await manager.async_configure(
            view["flow_id"], {"next_step_id": "tracked_apps"})
    assert view["description_placeholders"]["candidate"] == "chrome.exe"
    assert calls == [(topic, 0), ("unsubscribed", 0)]


@pytest.mark.parametrize("certificate, expected", [
    (None, "No"), ("auto", "Yes"), ("/secret/ca.pem", "Yes")])
async def test_mqtt_step_reports_tls_without_exposing_certificate(
        hass, enable_custom_integrations, certificate, expected):
    entry = add_device(hass, DATA1)
    mqtt_entry = SimpleNamespace(data={
        "broker": "mqtt.home.lan", "port": 8883, "certificate": certificate,
        "username": "private-user", "password": "private-password"}, options={})
    real_entries = hass.config_entries.async_entries

    def entries(domain=None, *args, **kwargs):
        return ([mqtt_entry] if domain == "mqtt"
                else real_entries(domain, *args, **kwargs))

    manager = hass.config_entries.options
    view = await manager.async_init(entry.entry_id)
    with patch.object(hass.config_entries, "async_entries", side_effect=entries), \
            patch.object(cf.mqtt, "is_connected", return_value=True):
        result = await manager.async_configure(
            view["flow_id"], {"next_step_id": "mqtt_settings"})
    rendered = json.dumps(result, default=str)
    assert result["description_placeholders"]["tls"] == expected
    assert "private-user" not in rendered
    assert "private-password" not in rendered
    assert "ca.pem" not in rendered


async def test_disconnected_mqtt_step_has_safe_navigation_hint(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    with patch.object(cf.mqtt, "is_connected", return_value=False):
        _, view = await open_step(hass, entry, "mqtt_settings")
    hint = view["description_placeholders"]["connection_help"]
    assert "Settings → Devices & services → MQTT" in hint
    assert "log" in hint.lower()


async def test_translations_explain_single_page_editor_and_mqtt(
        hass, enable_custom_integrations):
    for relative in ("strings.json", "translations/en.json"):
        steps = json.loads((PACKAGE / relative).read_text())["options"]["step"]
        assert set(steps) == {"menu", "mqtt_settings", "tracked_apps"}
        tracked = steps["tracked_apps"]["description"]
        assert "Detected foreground process" in tracked
        assert "Add item" in tracked
        assert "nothing is written to Windows" in tracked
        assert "applications" in steps["tracked_apps"]["data"]
        assert "shared" in steps["mqtt_settings"]["description"].lower()
        assert "{actions}" not in json.dumps(steps)


async def test_editor_replaces_top_level_save_without_resetting_legacy_settings(
        hass, enable_custom_integrations):
    saved = {"daily": 100, "weekly": 200, "enabled": True,
             "update_catalog_url": "https://example.com/catalog.json",
             "actions": ["terminate_game"], "unlimited": False}
    entry = add_device(hass, DATA1, saved)
    manager, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=ROBLOX)):
        result = await manager.async_configure(view["flow_id"], {
            "applications": [{"name": "Roblox", "detected": raw_label(ROBLOX)}]})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    for key, value in saved.items():
        assert result["data"][key] == value
    assert result["data"]["tracked_apps"][0]["name"] == "Roblox"
