"""One-screen tracked apps editor and safe HA/MQTT options flow."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hal_gaming_control import config_flow as cf
from custom_components.hal_gaming_control.app_editor import raw_label
from custom_components.hal_gaming_control.const import DOMAIN

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


async def open_step(hass, entry, step, candidate=None, raw="from_candidate"):
    manager = hass.config_entries.options
    view = await manager.async_init(entry.entry_id)
    if step == "tracked_apps":
        if raw == "from_candidate":
            raw = ({"state": "foreground", "process": candidate["process"],
                    "signature": candidate["signature"]} if candidate else None)
        with patch.object(cf, "_discover_foreground_candidate",
                          new=AsyncMock(return_value=candidate)), \
                patch.object(cf, "_discover_raw_foreground_snapshot",
                             new=AsyncMock(return_value=raw)):
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
    assert view["step_id"] == "settings_menu"
    assert view["menu_options"] == {"mqtt_settings": "MQTT configuration",
                                       "tracked_apps": "Tracked applications",
                                       "windows_updates": "Windows updates (advanced)",
                                       "screen_idle": "Screen idle (experimental)",
                                       "unified_telemetry": "Unified MQTT telemetry (experimental)"}
    assert entry.options == saved


async def test_real_home_assistant_options_translations_render_snapshot_and_labels(
        hass, enable_custom_integrations):
    """Catch missing translations that static JSON parity tests cannot detect."""
    from homeassistant.helpers.translation import async_get_translations

    key = f"component.{DOMAIN}.options.step.tracked_apps"
    for language in ("en", "hr"):
        resources = await async_get_translations(
            hass, language, "options", integrations={DOMAIN})
        assert resources[f"{key}.title"] == "Tracked applications"
        assert resources[f"{key}.data.applications"] == "Application List"
        assert resources[f"{key}.submit"] == "Save changes"
        description = resources[f"{key}.description"]
        assert "Currently detected application" in description
        assert "Save changes" in description
        assert "Currently detected application" in description
        assert "> ### {preview_name}" in description
        assert "> `{raw_value}`" in description
        assert "**Note**" in description
        assert "Displayed as" not in description
        assert "Raw sensor value:" not in description
        assert description.rstrip().endswith("---")

    entry = add_device(hass, DATA1, {"tracked_apps": [{
        "process": ROBLOX["process"], "signature": None, "name": "Roblox"}]})
    _, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    assert view["step_id"] == "tracked_apps"
    placeholders = view["description_placeholders"]
    rendered = description.format(**placeholders)
    assert "> ### Roblox" in rendered
    assert "> `RobloxPlayerBeta.exe`" in rendered
    assert "**Note**" in rendered
    assert "{raw_value}" not in rendered
    assert "{preview_name}" not in rendered


async def test_one_form_shows_existing_name_and_raw_process(
        hass, enable_custom_integrations):
    old = [{"process": "javaw.exe", "signature": MINECRAFT["signature"],
            "name": "Minecraft Java"}]
    entry = add_device(hass, DATA1, {"tracked_apps": old, "daily": 90})
    manager, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    assert view["type"] == data_entry_flow.FlowResultType.FORM
    assert view["step_id"] == "tracked_apps"
    assert view["description_placeholders"]["raw_value"] == "RobloxPlayerBeta.exe"
    assert view["description_placeholders"]["preview_name"] == "Not tracked"
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
    assert view["description_placeholders"]["raw_value"] == "unavailable"
    assert view["description_placeholders"]["preview_name"] == "Unavailable"
    assert "tracked_apps" not in entry.options
    assert "Minecraft" not in json.dumps(view, default=str)


async def test_raw_snapshot_maps_registered_name_without_changing_app_list(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"tracked_apps": [{
        "process": ROBLOX["process"], "signature": None, "name": "Roblox"}]})
    _, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    assert view["description_placeholders"]["raw_value"] == "RobloxPlayerBeta.exe"
    assert view["description_placeholders"]["preview_name"] == "Roblox"
    assert rows(view) == [{"name": "Roblox", "detected": "RobloxPlayerBeta.exe"}]


@pytest.mark.parametrize("raw, process, friendly", [
    ({"state": "foreground", "process": "chrome.exe", "signature": None},
     "chrome.exe", "Not tracked"),
    ({"state": "idle", "process": None, "signature": None}, "idle", "Idle"),
    ({"state": "unknown", "process": None, "signature": None},
     "unknown", "Unavailable"),
    (None, "unavailable", "Unavailable"),
])
async def test_raw_foreground_preview_has_fail_closed_display(
        hass, enable_custom_integrations, raw, process, friendly):
    entry = add_device(hass, DATA1)
    _, view = await open_step(hass, entry, "tracked_apps", raw=raw)
    assert view["description_placeholders"]["raw_value"] == process
    assert view["description_placeholders"]["preview_name"] == friendly
    assert rows(view) == []


async def test_java_signature_is_visible_and_matched_to_friendly_alias(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"tracked_apps": [{
        "process": "javaw.exe", "signature": MINECRAFT["signature"],
        "name": "Minecraft"}]})
    _, view = await open_step(hass, entry, "tracked_apps", MINECRAFT)
    assert view["description_placeholders"]["raw_value"] == (
        "javaw.exe — java_class: net.minecraft.client.main.Main")
    assert view["description_placeholders"]["preview_name"] == "Minecraft"


async def test_preview_escapes_markdown_punctuation_in_saved_display_name(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1, {"tracked_apps": [{
        "process": ROBLOX["process"], "signature": None,
        "name": "Roblox *Family*"}]})
    _, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    assert view["description_placeholders"]["preview_name"] == r"Roblox \*Family\*"
    # Stored friendly name and list editor remain unmodified.
    assert rows(view) == [
        {"name": "Roblox *Family*", "detected": "RobloxPlayerBeta.exe"}]


async def test_preview_presents_untracked_and_idle_as_distinct_states(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    _, untracked = await open_step(hass, entry, "tracked_apps", raw={
        "state": "foreground", "process": "chrome.exe", "signature": None})
    _, idle = await open_step(hass, entry, "tracked_apps", raw={
        "state": "idle", "process": None, "signature": None})
    assert untracked["description_placeholders"]["preview_name"] == "Not tracked"
    assert untracked["description_placeholders"]["raw_value"] == "chrome.exe"
    assert idle["description_placeholders"]["preview_name"] == "Idle"
    assert idle["description_placeholders"]["raw_value"] == "idle"


async def test_raw_identity_change_prevents_cross_app_add_default(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    _, view = await open_step(
        hass, entry, "tracked_apps", ROBLOX,
        raw={"state": "foreground", "process": "chrome.exe", "signature": None})
    assert view["description_placeholders"]["raw_value"] == "chrome.exe"
    assert view["description_placeholders"]["preview_name"] == "Not tracked"
    field = next(iter(view["data_schema"].schema.values()))
    assert field.config["fields"]["detected"].get("default") is None


async def test_raw_snapshot_rejects_stale_retained_foreign_and_unsafe_packets(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    device_topic = "SmartHouse/Gaming/pc1/state/foreground_identity"
    now = cf.dt_util.utcnow().timestamp()
    base = {"version": 2, "device_id": "pc1", "epoch": "a" * 32,
            "sequence": 1, "observed_at": now,
            "state": "foreground", "process": "chrome.exe", "signature": None}
    captured = []

    async def subscribe(_hass, topic, cb, qos=0):
        captured.append((topic, qos))
        cb(SimpleNamespace(topic=device_topic, payload=json.dumps(base),
                           retain=True))
        cb(SimpleNamespace(topic=device_topic, payload=json.dumps(
            base | {"device_id": "pc2"}), retain=False))
        cb(SimpleNamespace(topic=device_topic, payload=json.dumps(
            base | {"process": "C:/private/file.exe"}), retain=False))
        cb(SimpleNamespace(topic=device_topic, payload=json.dumps(
            base | {"observed_at": now - 90}), retain=False))
        cb(SimpleNamespace(topic=device_topic, payload=json.dumps(base),
                           retain=False))
        return lambda: captured.append(("unsubscribed", 0))

    with patch.object(cf.mqtt, "async_subscribe", side_effect=subscribe), \
            patch.object(cf, "_listen_window", new=AsyncMock()), \
            patch.object(cf, "_discover_foreground_candidate",
                         new=AsyncMock(return_value=None)):
        manager = hass.config_entries.options
        view = await manager.async_init(entry.entry_id)
        view = await manager.async_configure(
            view["flow_id"], {"next_step_id": "tracked_apps"})
    assert captured == [(device_topic, 0), ("unsubscribed", 0)]
    assert view["description_placeholders"]["raw_value"] == "chrome.exe"
    assert view["description_placeholders"]["preview_name"] == "Not tracked"


def v3_roblox_packet(*, device="pc1", observed_at, state="foreground", age_ms=50):
    return {
        "version": 3, "device_id": device, "epoch": "c" * 32,
        "sequence": 1, "observed_at": observed_at,
        "foreground": {
            "state": state,
            "process": "RobloxPlayerBeta.exe" if state == "foreground" else None,
            "signature": None, "sample_age_ms": age_ms,
        },
        "display": {
            "state": "unknown", "scope": "windows_console",
            "event_epoch": None, "event_sequence": None,
            "event_age_ms": None, "sample_age_ms": None,
            "ac_timeout_seconds": None, "dc_timeout_seconds": None,
            "power_source": "unknown", "last_input_idle_ms": None,
        },
        "system": {
            "uptime_seconds": 1234, "agent_version": "0.3.0",
            "agent_build_sha": None,
        },
    }


async def test_v3_only_windows_agent_shows_detected_app_in_editor(
        hass, enable_custom_integrations):
    """Preview must work without old v2 MQTT, even if v3 accounting is disabled."""
    entry = add_device(hass, DATA1)
    now = cf.dt_util.utcnow().timestamp()
    v3_topic = "SmartHouse/Gaming/pc1/state/telemetry"
    subscriptions = []

    async def subscribe(_hass, topic, cb, qos=0):
        subscriptions.append(topic)
        if topic == v3_topic:
            cb(SimpleNamespace(topic=topic, retain=False,
                               payload=json.dumps(v3_roblox_packet(observed_at=now))))
        return lambda: None

    with patch.object(cf.mqtt, "async_subscribe", side_effect=subscribe), \
            patch.object(cf, "_listen_window", new=AsyncMock()), \
            patch.object(cf, "_discover_foreground_candidate",
                         new=AsyncMock(return_value=ROBLOX)):
        manager = hass.config_entries.options
        menu = await manager.async_init(entry.entry_id)
        result = await manager.async_configure(
            menu["flow_id"], {"next_step_id": "tracked_apps"})

    assert v3_topic in subscriptions
    assert result["description_placeholders"]["raw_value"] == "RobloxPlayerBeta.exe"
    assert result["description_placeholders"]["preview_name"] == "Not tracked"
    assert rows(result) == []
    field = next(iter(result["data_schema"].schema.values()))
    assert field.config["fields"]["detected"]["default"] == "RobloxPlayerBeta.exe"


async def test_v3_rejects_retained_foreign_stale_and_unsafe_preview(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    now = cf.dt_util.utcnow().timestamp()
    v3_topic = "SmartHouse/Gaming/pc1/state/telemetry"

    async def subscribe(_hass, topic, cb, qos=0):
        if topic == v3_topic:
            valid = v3_roblox_packet(observed_at=now)
            for packet, retained in (
                    (valid, True),
                    (valid | {"device_id": "pc2"}, False),
                    (valid | {"observed_at": now - 90}, False),
                    (valid | {"foreground": valid["foreground"] |
                              {"process": "C:/unsafe.exe"}}, False)):
                cb(SimpleNamespace(topic=topic, retain=retained,
                                   payload=json.dumps(packet)))
        return lambda: None

    with patch.object(cf.mqtt, "async_subscribe", side_effect=subscribe), \
            patch.object(cf, "_listen_window", new=AsyncMock()), \
            patch.object(cf, "_discover_foreground_candidate",
                         new=AsyncMock(return_value=None)):
        manager = hass.config_entries.options
        menu = await manager.async_init(entry.entry_id)
        result = await manager.async_configure(
            menu["flow_id"], {"next_step_id": "tracked_apps"})

    assert result["description_placeholders"]["raw_value"] == "unavailable"
    assert result["description_placeholders"]["preview_name"] == "Unavailable"


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
    probe.assert_not_awaited()
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


@pytest.mark.parametrize("later", [
    MINECRAFT | {"token": "b" * 32},
    ROBLOX,
    None,
])
async def test_captured_application_can_be_added_after_alt_tab_or_exit(
        hass, enable_custom_integrations, later):
    entry = add_device(hass, DATA1)
    manager, view = await open_step(hass, entry, "tracked_apps", MINECRAFT)
    assert view["description_placeholders"]["raw_value"].startswith("javaw.exe")
    # No additional sample is needed at Submit, even hours later in the same flow.
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=later)) as candidate_probe, \
            patch.object(cf, "_discover_raw_foreground_snapshot",
                         new=AsyncMock(return_value=None)) as raw_probe:
        result = await manager.async_configure(view["flow_id"], {"applications": [
            {"name": "Minecraft", "detected": raw_label(MINECRAFT)}]})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["tracked_apps"] == [
        {"process": "javaw.exe", "signature": MINECRAFT["signature"],
         "name": "Minecraft"}]
    candidate_probe.assert_not_awaited()
    raw_probe.assert_not_awaited()


async def test_capture_starts_only_after_selecting_tracked_apps_and_reopen_recaptures(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    manager = hass.config_entries.options
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=ROBLOX)) as candidate_probe, \
            patch.object(cf, "_discover_raw_foreground_snapshot",
                         new=AsyncMock(return_value={
                             "state": "foreground", "process": ROBLOX["process"],
                             "signature": None})) as raw_probe:
        menu = await manager.async_init(entry.entry_id)
        assert menu["step_id"] == "settings_menu"
        candidate_probe.assert_not_awaited()
        raw_probe.assert_not_awaited()
        first = await manager.async_configure(
            menu["flow_id"], {"next_step_id": "tracked_apps"})
    assert first["description_placeholders"]["raw_value"] == ROBLOX["process"]
    candidate_probe.assert_awaited_once()
    raw_probe.assert_awaited_once()

    # Leaving Configure and opening a NEW Options Flow recaptures, without
    # cross-flow reuse of the previous executable, signature or token.
    manager2 = hass.config_entries.options
    menu2 = await manager2.async_init(entry.entry_id)
    with patch.object(cf, "_discover_foreground_candidate",
                      new=AsyncMock(return_value=MINECRAFT)), \
            patch.object(cf, "_discover_raw_foreground_snapshot",
                         new=AsyncMock(return_value={
                             "state": "foreground", "process": "javaw.exe",
                             "signature": MINECRAFT["signature"]})):
        second = await manager2.async_configure(
            menu2["flow_id"], {"next_step_id": "tracked_apps"})
    assert second["description_placeholders"]["raw_value"] == raw_label(MINECRAFT)
    with pytest.raises(data_entry_flow.InvalidData):
        await manager2.async_configure(second["flow_id"], {"applications": [
            {"name": "Old Roblox", "detected": raw_label(ROBLOX)}]})
    assert "tracked_apps" not in entry.options


async def test_capture_survives_validation_errors_without_resubscribing(
        hass, enable_custom_integrations):
    entry = add_device(hass, DATA1)
    manager, view = await open_step(hass, entry, "tracked_apps", ROBLOX)
    with patch.object(cf, "_discover_foreground_candidate", new=AsyncMock()) as probe:
        invalid = await manager.async_configure(view["flow_id"], {
            "applications": [{"name": "idle", "detected": raw_label(ROBLOX)}]})
        assert invalid["errors"]["base"] == "invalid_application"
        assert invalid["description_placeholders"]["raw_value"] == raw_label(ROBLOX)
        corrected = await manager.async_configure(invalid["flow_id"], {
            "applications": [{"name": "Roblox", "detected": raw_label(ROBLOX)}]})
    assert corrected["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert corrected["data"]["tracked_apps"][0]["name"] == "Roblox"
    probe.assert_not_awaited()


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
    assert view["description_placeholders"]["raw_value"] == "javaw.exe"
    assert view["description_placeholders"]["preview_name"] == "Unavailable"
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
            patch.object(cf, "_listen_window", new=AsyncMock()), \
            patch.object(cf, "_discover_raw_foreground_snapshot",
                         new=AsyncMock(return_value=None)):
        view = await manager.async_configure(
            view["flow_id"], {"next_step_id": "tracked_apps"})
    assert view["description_placeholders"]["raw_value"] == "unavailable"
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
        assert set(steps) == {"settings_menu", "mqtt_settings", "tracked_apps", "windows_updates", "screen_idle", "unified_telemetry"}
        assert steps["settings_menu"]["menu_options"] == {
            "mqtt_settings": "MQTT configuration",
            "tracked_apps": "Tracked applications",
            "windows_updates": "Windows updates (advanced)",
            "screen_idle": "Screen idle (experimental)",
                                       "unified_telemetry": "Unified MQTT telemetry (experimental)",
        }
        assert "{actions}" not in steps["settings_menu"]["description"]
        assert steps["settings_menu"]["title"] == "HAL Gaming Control"
        assert steps["tracked_apps"]["submit"] == "Save changes"
        assert "submit" not in steps["mqtt_settings"]
        tracked = steps["tracked_apps"]["description"]
        assert "Currently detected application" in tracked
        assert "Use Add to enroll" in tracked
        assert "\\n" not in tracked  # Real Markdown line breaks, not literal \\n sequences
        assert "nothing is written to Windows" in tracked
        assert "Currently detected application" in tracked
        assert "> ### {preview_name}" in tracked
        assert "> `{raw_value}`" in tracked
        assert "**Note**" in tracked
        assert "Save changes" in tracked
        assert "Displayed as" not in tracked
        assert "Raw sensor value:" not in tracked
        assert tracked.rstrip().endswith("---")
        assert "snapshot" in tracked.lower()
        assert "switches apps or exits" in tracked.lower()
        assert "close and reopen" in tracked.lower()
        assert steps["tracked_apps"]["data"]["applications"] == "Application List"
        assert "applications" in steps["tracked_apps"]["data"]
        assert "shared" in steps["mqtt_settings"]["description"].lower()
        assert "{actions}" not in json.dumps(steps)
        errors = json.loads((PACKAGE / relative).read_text())["options"]["error"]
        assert "invalid_time" not in errors
        assert "invalid_catalog" not in errors


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
