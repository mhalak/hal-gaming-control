"""Exercise the actual Home Assistant flow manager, not a reimplemented UI."""
import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from homeassistant import config_entries, data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.smarthouse_gaming.const import DOMAIN
from custom_components.smarthouse_gaming.config_flow import GamingConfigFlow
from custom_components.smarthouse_gaming.coordinator import GamingCoordinator

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures('recorder_mock')]

DATA = {"device_id":"pc1","name":"Gaming PC 1","protocol_version":1,
        "games":["Minecraft","Roblox"],"actions":["terminate_game","lock_pc"]}

async def test_discovery_flow(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT},
        data=SimpleNamespace(topic="SmartHouse/Gaming/pc1/discovery", payload=json.dumps(DATA)))
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["name"] == "Gaming PC 1"

async def test_invalid_discovery(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT},
        data=SimpleNamespace(topic="SmartHouse/Gaming/other/discovery", payload=json.dumps(DATA)))
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery"

async def test_options_menu_preserves_legacy_actions_but_no_action_editor(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain=DOMAIN, title=DATA["name"], data=DATA,
                            unique_id="pc1", options={"actions": ["terminate_game"]})
    entry.add_to_hass(hass)
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "limits", "mqtt_settings", "update_settings", "save"}
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "save"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    # Do not destroy legacy action options; they can no longer cause automatic commands.
    assert entry.options["actions"] == ["terminate_game"]


async def test_remote_update_entity_request_and_completion(hass):
    from unittest.mock import AsyncMock, Mock
    from custom_components.smarthouse_gaming.update import WindowsAgentUpdate
    from homeassistant.exceptions import HomeAssistantError

    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry.data = DATA
    coordinator.data = {"online": True}
    entity = WindowsAgentUpdate(coordinator)
    entity.hass = hass
    with patch.object(entity, "async_write_ha_state"), patch.object(entity, "_refresh_catalog", new_callable=AsyncMock), patch("custom_components.smarthouse_gaming.update.mqtt.async_publish", new_callable=AsyncMock) as publish:
        entity._metadata(SimpleNamespace(topic="SmartHouse/Gaming/pc1/discovery",payload=json.dumps(DATA | {"agent_version":"0.1.0","remote_update":True})))
        entity.approved = "0.2.0"
        assert entity.available
        with pytest.raises(HomeAssistantError):
            await entity.async_install("0.3.0", False)
        await entity.async_install(None, False)
        assert entity.in_progress
        args = publish.call_args.args
        assert args[1] == "SmartHouse/Gaming/pc1/command/update"
        assert publish.call_args.kwargs == {"qos":0,"retain":False}
        request = json.loads(args[2])
        assert request["version"] == "0.2.0"
        payload = {"request_id":request["request_id"],"version":"0.2.0","status":"success","timestamp":1000}
        entity._status(SimpleNamespace(payload=json.dumps(payload | {"request_id":"00000000-0000-0000-0000-000000000000"})))
        assert entity.result == "requested"
        entity._status(SimpleNamespace(payload=json.dumps(payload)))
        assert entity.in_progress  # status alone is not installation proof
        entity._metadata(SimpleNamespace(topic="SmartHouse/Gaming/pc1/discovery",payload=json.dumps(DATA | {"agent_version":"0.2.0","remote_update":True})))
        assert not entity.in_progress
        assert entity.installed_version == "0.2.0"

async def test_remote_update_restore_after_restart(hass):
    from time import time
    from unittest.mock import Mock
    from custom_components.smarthouse_gaming.update import WindowsAgentUpdate, TIMEOUT
    from custom_components.smarthouse_gaming.update_protocol import make_request
    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry.data = DATA
    coordinator.data = {"online": False}
    request = make_request("0.1.0", "0.2.0", time())
    entity = WindowsAgentUpdate(coordinator)
    entity.hass = hass
    saved = {"pending":request, "deadline":time()+TIMEOUT-30, "result":"installing"}
    entity._restore(saved)
    assert entity.in_progress and entity.available
    with patch.object(entity, "async_write_ha_state"):
        entity._status(SimpleNamespace(payload=json.dumps({"request_id":request["request_id"],"version":"0.2.0","status":"success","timestamp":1000})))
        assert entity.in_progress
        entity._metadata(SimpleNamespace(topic="SmartHouse/Gaming/pc1/discovery",payload=json.dumps(DATA | {"agent_version":"0.2.0","remote_update":True})))
        assert not entity.in_progress
    assert entity._snapshot()["result"] == "success"
    expired = WindowsAgentUpdate(coordinator)
    expired._restore(saved | {"deadline":time()-1})
    assert not expired.in_progress
    assert expired.result == "timeout_unconfirmed"


async def test_mqtt_manifest_subscription_dispatches_real_discovery(hass, enable_custom_integrations):
    """Exercise HA loader, subscription registration and discovery dispatcher.

    Only transport subscription is stubbed. Do not patch the HA MQTT manifest map
    or call our config flow directly: those would miss the production failure.
    """
    import asyncio
    from homeassistant.components.mqtt import discovery
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.loader import async_get_mqtt

    matcher = "SmartHouse/Gaming/+/discovery"
    assert matcher in (await async_get_mqtt(hass))[DOMAIN]
    subscriptions = {}
    def subscribe(_hass, topic, handler, qos, **kwargs):
        subscriptions[topic] = handler
        return lambda: None

    fake = SimpleNamespace(discovery_unsubscribe=[], integration_unsubscribe={},
                           data_config_flow_lock=asyncio.Lock(), last_discovery=0)
    entry = MockConfigEntry(domain="mqtt", data={"broker":"example.invalid"})
    # Restore MQTT dependency state before dispatch actually initializes the flow.
    with patch.dict(hass.data, {discovery.DATA_MQTT:fake}):
        with patch.object(discovery, "async_subscribe_internal", side_effect=subscribe):
            await discovery.async_start(hass, "homeassistant", entry)
            assert matcher in subscriptions
            handler = subscriptions[matcher]
            await discovery.async_stop(hass)

    payload = DATA | {"device_id":"gaming_pc_01","name":"Gaming PC 1",
                      "games":["Minecraft Java","Minecraft Bedrock","Roblox"],
                      "agent_version":"0.1.0","remote_update":False}
    message = SimpleNamespace(topic="SmartHouse/Gaming/gaming_pc_01/discovery",
                              payload=json.dumps(payload), qos=1, retain=True,
                              subscribed_topic=matcher, timestamp=1.0)
    await handler(message)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done(wait_background_tasks=True)
    flows = [flow for flow in hass.config_entries.flow.async_progress()
             if flow["handler"] == DOMAIN]
    assert len(flows) == 1
    assert flows[0]["step_id"] == "confirm"
    assert flows[0]["context"]["source"] == config_entries.SOURCE_MQTT
    await handler(message)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len([f for f in hass.config_entries.flow.async_progress() if f["handler"] == DOMAIN]) == 1

# --- Manual onboarding when HA MQTT discovery is disabled (issue #13) ---
from unittest.mock import MagicMock
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message
from custom_components.smarthouse_gaming import config_flow as cf

@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client leaves a housekeeping timer."""
    return True


DISCOVERY_FILTER = "SmartHouse/Gaming/+/discovery"
DATA2 = {"device_id": "pc2", "name": "Gaming PC 2", "protocol_version": 1,
         "games": ["Fortnite"], "actions": ["lock_pc"]}


def msg(device_id, payload):
    body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    return SimpleNamespace(topic=f"SmartHouse/Gaming/{device_id}/discovery", payload=body)


@pytest.fixture
def fake_mqtt():
    """Replace the mqtt subscription used by the config flow; deliver retained messages on subscribe."""
    state = SimpleNamespace(messages=[], filters=[], unsub=MagicMock(), raise_on_subscribe=None)

    async def subscribe(hass, topic, callback, *args, **kwargs):
        if state.raise_on_subscribe:
            raise state.raise_on_subscribe
        state.filters.append(topic)
        for message in state.messages:
            callback(message)
        return state.unsub

    async def no_wait():
        return None

    with patch.object(cf.mqtt, "async_subscribe", side_effect=subscribe), \
            patch.object(cf, "_listen_window", no_wait):
        yield state


async def start_user(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


def option_values(result):
    options = result["data_schema"].schema["device"].config["options"]
    return [o["value"] for o in options]


async def test_user_flow_creates_entry_with_same_data_as_confirm(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.messages = [msg("pc1", DATA)]
    result = await start_user(hass)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"
    assert option_values(result) == ["pc1"]
    assert fake_mqtt.filters == [DISCOVERY_FILTER]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "pc1"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gaming PC 1"
    assert result["data"] == DATA
    assert result["result"].unique_id == "pc1"
    fake_mqtt.unsub.assert_called_once()


async def test_user_flow_data_identical_to_mqtt_path(hass, enable_custom_integrations, fake_mqtt):
    mqtt_result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT}, data=msg("pc1", DATA))
    mqtt_result = await hass.config_entries.flow.async_configure(mqtt_result["flow_id"], {})
    fake_mqtt.messages = [msg("pc2", {**DATA, "device_id": "pc2"})]
    result = await start_user(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "pc2"})
    assert set(result["data"]) == set(mqtt_result["data"])
    assert result["data"] == {**DATA, "device_id": "pc2"}


async def test_user_flow_two_devices_selectable(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.messages = [msg("pc2", DATA2), msg("pc1", DATA)]
    result = await start_user(hass)
    assert option_values(result) == ["pc1", "pc2"]
    labels = {o["value"]: o["label"] for o in result["data_schema"].schema["device"].config["options"]}
    assert labels == {"pc1": "Gaming PC 1", "pc2": "Gaming PC 2"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "pc2"})
    assert result["data"] == DATA2
    assert result["result"].unique_id == "pc2"


async def test_user_flow_filters_configured_devices(hass, enable_custom_integrations, fake_mqtt):
    MockConfigEntry(domain=DOMAIN, title=DATA["name"], data=DATA, unique_id="pc1").add_to_hass(hass)
    fake_mqtt.messages = [msg("pc1", DATA), msg("pc2", DATA2)]
    result = await start_user(hass)
    assert option_values(result) == ["pc2"]


async def test_user_flow_all_configured_is_no_devices_found(hass, enable_custom_integrations, fake_mqtt):
    MockConfigEntry(domain=DOMAIN, title=DATA["name"], data=DATA, unique_id="pc1").add_to_hass(hass)
    fake_mqtt.messages = [msg("pc1", DATA)]
    result = await start_user(hass)
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"
    fake_mqtt.unsub.assert_called_once()


async def test_user_flow_no_messages_is_no_devices_found(hass, enable_custom_integrations, fake_mqtt):
    result = await start_user(hass)
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"
    fake_mqtt.unsub.assert_called_once()


BAD_PAYLOADS = {
    "not_json": "{nope",
    "not_object": "[1, 2]",
    "wrong_protocol": json.dumps({**DATA, "protocol_version": 2}),
    "id_mismatch": json.dumps({**DATA, "device_id": "other"}),
    "bad_name": json.dumps({**DATA, "name": " "}),
    "bad_games": json.dumps({**DATA, "games": "Minecraft"}),
    "oversized": json.dumps({**DATA, "name": "x" * 200000}),
    "none_payload": None,
    "invalid_bytes": b"\xff\xfe\x00",
    "int_payload": 5,
}


@pytest.mark.parametrize("bad", list(BAD_PAYLOADS))
async def test_user_flow_ignores_invalid_payload(hass, enable_custom_integrations, fake_mqtt, bad):
    fake_mqtt.messages = [msg("pc1", BAD_PAYLOADS[bad]), msg("pc2", DATA2)]
    result = await start_user(hass)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert option_values(result) == ["pc2"]
    fake_mqtt.unsub.assert_called_once()


async def test_user_flow_foreign_topic_ignored(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.messages = [SimpleNamespace(topic="homeassistant/sensor/x/config", payload=json.dumps(DATA)),
                          SimpleNamespace(topic="SmartHouse/Gaming/pc1/discovery/extra", payload=json.dumps(DATA))]
    result = await start_user(hass)
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_only_invalid_is_no_devices_found(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.messages = [msg("pc1", "{nope")]
    result = await start_user(hass)
    assert result["reason"] == "no_devices_found"


async def test_user_flow_unsubscribes_when_wait_fails(hass, enable_custom_integrations, fake_mqtt):
    async def broken_wait():
        raise RuntimeError("boom")
    with patch.object(cf, "_listen_window", broken_wait):
        with pytest.raises(Exception):
            await start_user(hass)
    fake_mqtt.unsub.assert_called_once()


async def test_user_flow_subscribe_error_is_no_devices_found(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.raise_on_subscribe = RuntimeError("mqtt not available")
    result = await start_user(hass)
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_rejects_unknown_selection(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.messages = [msg("pc1", DATA)]
    result = await start_user(hass)
    with pytest.raises(Exception):
        await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "ghost"})
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_user_flow_device_configured_meanwhile_aborts(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.messages = [msg("pc1", DATA)]
    result = await start_user(hass)
    MockConfigEntry(domain=DOMAIN, title=DATA["name"], data=DATA, unique_id="pc1").add_to_hass(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "pc1"})
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_user_then_mqtt_no_duplicate(hass, enable_custom_integrations, fake_mqtt):
    fake_mqtt.messages = [msg("pc1", DATA)]
    result = await start_user(hass)
    await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "pc1"})
    again = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT}, data=msg("pc1", DATA))
    assert again["type"] == data_entry_flow.FlowResultType.ABORT
    assert again["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_mqtt_then_user_no_duplicate(hass, enable_custom_integrations, fake_mqtt):
    pending = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT}, data=msg("pc1", DATA))
    assert pending["step_id"] == "confirm"
    fake_mqtt.messages = [msg("pc1", DATA)]
    result = await start_user(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "pc1"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_mqtt_path_regression_confirm_creates_entry(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT}, data=msg("pc1", DATA))
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == DATA
    assert result["result"].unique_id == "pc1"


async def test_user_flow_real_mqtt_subscription(hass, enable_custom_integrations, mqtt_mock):
    """Real mqtt.async_subscribe: wildcard match, retained delivery inside the window, unsubscribe afterwards."""
    async def window():
        async_fire_mqtt_message(hass, "SmartHouse/Gaming/pc1/discovery", json.dumps(DATA))
        async_fire_mqtt_message(hass, "SmartHouse/Gaming/pc2/discovery", "garbage")
        async_fire_mqtt_message(hass, "SmartHouse/Other/pc3/discovery", json.dumps(DATA2))
        await hass.async_block_till_done()
    real_subscribe = cf.mqtt.async_subscribe
    unsubs = []

    async def spy(*args, **kwargs):
        unsub = await real_subscribe(*args, **kwargs)
        wrapped = MagicMock(side_effect=unsub)
        unsubs.append((args[1], wrapped))
        return wrapped

    with patch.object(cf.mqtt, "async_subscribe", side_effect=spy), patch.object(cf, "_listen_window", window):
        result = await start_user(hass)
    assert option_values(result) == ["pc1"]
    assert [topic for topic, _ in unsubs] == [DISCOVERY_FILTER]
    unsubs[0][1].assert_called_once()
    # after the window the subscription is gone: later messages must not alter the flow
    async_fire_mqtt_message(hass, "SmartHouse/Gaming/pc2/discovery", json.dumps(DATA2))
    await hass.async_block_till_done()
    assert option_values(result) == ["pc1"]


async def test_window_is_bounded():
    assert 0 < cf.DISCOVERY_WINDOW <= 10


def test_strings_cover_manual_onboarding():
    import pathlib
    base = pathlib.Path(cf.__file__).parent
    for rel in ("strings.json", "translations/en.json"):
        config = json.loads((base / rel).read_text())["config"]
        assert config["step"]["user"]["data"]["device"]
        assert config["abort"]["no_devices_found"]
        assert "discovery_only" not in config["abort"]


async def test_limit_form_excludes_override_and_legacy_weekend_total(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="pc1",
                            options={"daily":60,"weekend_daily":120,"weekend_total":90,"unlimited":False})
    entry.add_to_hass(hass)
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    result = await manager.async_configure(result["flow_id"], {"next_step_id":"limits"})
    fields = {str(k) for k in result["data_schema"].schema}
    assert fields == {"enabled","reset_daily","reset_weekly","reset_weekend_daily","schedule_enabled","schedule_start","schedule_end"}
    result = await manager.async_configure(result["flow_id"], {"enabled":True,"schedule_enabled":False,
        "schedule_start":"16:00","schedule_end":"20:00"})
    hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {"unlimited":True,"daily":90,"bonus_date":"2026-11-18","bonus_minutes":30,"actions":["lock_pc"]})
    result = await manager.async_configure(result["flow_id"], {"next_step_id":"save"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.options["unlimited"] is True
    assert entry.options["weekend_daily"] == 120
    assert entry.options["daily"] == 90
    assert entry.options["bonus_minutes"] == 30
    assert entry.options["actions"] == ["lock_pc"]
    assert "weekend_total" not in entry.options


@pytest.mark.parametrize("connected,direct", [(True,True),(False,False)])
async def test_mqtt_configuration_info_is_scoped_and_read_only(hass, enable_custom_integrations, connected, direct):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="pc1", options={"daily":60})
    entry.add_to_hass(hass)
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert "mqtt_settings" in result["menu_options"]
    with patch.object(cf.mqtt, "is_connected", return_value=connected), patch.object(cf, "direct_mode", return_value=direct):
        result = await manager.async_configure(result["flow_id"], {"next_step_id":"mqtt_settings"})
    assert result["step_id"] == "mqtt_settings"
    assert result["description_placeholders"] == {
        "connection": "Connected" if connected else "Disconnected",
        "device_id": "pc1",
        "root": "SmartHouse/Gaming/pc1",
        "mode": "Scoped discovery" if direct else "Native MQTT discovery",
        "broker": "Not configured",
        "port": "Unknown",
    }
    assert not result["data_schema"].schema
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert entry.options == {"daily":60}


async def test_per_game_editor_hidden_preserving_existing_settings(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="pc1",
                            options={"daily":60,"per_game":{"Roblox":30}})
    entry.add_to_hass(hass)
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert "game_limits" not in result["menu_options"]
    assert "mqtt_settings" in result["menu_options"]
    assert "update_settings" in result["menu_options"]
    # Preserve concurrent updates to the now-hidden legacy setting.
    hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {
        "per_game":{"Roblox":45}})
    result = await manager.async_configure(result["flow_id"], {"next_step_id":"save"})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.options["per_game"] == {"Roblox":45}
    assert entry.options["daily"] == 60


def test_per_game_editor_translations_removed():
    from pathlib import Path
    parent = Path(cf.__file__).parent
    for rel in ("strings.json","translations/en.json"):
        steps = json.loads((parent / rel).read_text())["options"]["step"]
        assert not {"game_limits","choose_game","game_limit"} & steps.keys()


@pytest.mark.parametrize("key, platform", [("current_game", "sensor"), ("lock_pc", "button"),
                                          ("update", "update")])
async def test_cross_domain_registry_transfer_and_reverse(hass, key, platform):
    """Capability test against the real HA registries, not a mock migration implementation."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    options = {"daily": 60, "weekly": 300, "weekend_daily": 120, "unlimited": True,
               "bonus_minutes": 30, "bonus_date": "2026-11-20", "actions": ["lock_pc"]}
    old = MockConfigEntry(domain=DOMAIN, title=DATA["name"], data=DATA,
                          options=options, unique_id="pc1")
    new = MockConfigEntry(domain="parental", title=old.title, data=dict(old.data),
                          options=dict(old.options), unique_id=old.unique_id)
    old.add_to_hass(hass)
    new.add_to_hass(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    identifiers = {("mqtt", "smarthouse_gaming_pc1")}
    device = devices.async_get_or_create(config_entry_id=old.entry_id, identifiers=identifiers,
                                         name="Test PC")
    devices.async_update_device(device.id, name_by_user="Custom PC")
    entity = entities.async_get_or_create(platform, DOMAIN, "pc1_" + key,
                                           config_entry=old, device_id=device.id)
    entity = entities.async_update_entity(entity.entity_id, name="Custom entity",
                                          disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()

    # The entity and device must move in one synchronous registry operation group.
    # Both entries are unloaded in this test. Never move live entities.
    entities.async_update_entity_platform(entity.entity_id, "parental",
                                          new_config_entry_id=new.entry_id)
    devices.async_update_device(device.id, new_config_entry_id=new.entry_id)
    await hass.async_block_till_done()

    moved = entities.async_get(entity.entity_id)
    assert moved is not None
    assert moved.id == entity.id and moved.unique_id == entity.unique_id
    assert moved.entity_id == entity.entity_id and moved.device_id == device.id
    assert moved.platform == "parental" and moved.config_entry_id == new.entry_id
    assert moved.name == "Custom entity" and moved.disabled_by == er.RegistryEntryDisabler.USER
    assert entities.async_get_entity_id(platform, DOMAIN, entity.unique_id) is None
    assert entities.async_get_entity_id(platform, "parental", entity.unique_id) == entity.entity_id
    target_device = devices.async_get(device.id)
    assert target_device.config_entry_id == new.entry_id
    assert target_device.identifiers == identifiers and target_device.name_by_user == "Custom PC"
    assert dict(new.options) == dict(old.options) == options
    assert dict(new.data) == dict(old.data) == DATA

    # Prove the registry operations can be reversed before retiring the old entry.
    entities.async_update_entity_platform(entity.entity_id, DOMAIN,
                                          new_config_entry_id=old.entry_id)
    devices.async_update_device(device.id, new_config_entry_id=old.entry_id)
    await hass.async_block_till_done()
    restored = entities.async_get(entity.entity_id)
    assert restored is not None and restored.id == entity.id
    assert restored.platform == DOMAIN and restored.config_entry_id == old.entry_id
    assert restored.device_id == device.id and restored.disabled_by == entity.disabled_by
    assert devices.async_get(device.id).config_entry_id == old.entry_id
    assert entities.async_get_entity_id(platform, "parental", entity.unique_id) is None


async def test_cross_domain_transfer_preserves_native_mqtt_and_other_pc(hass):
    """HA 2026.10 device ownership is scoped to the config entry, not the identifier alone."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    legacy = MockConfigEntry(domain=DOMAIN, unique_id="pc1", data=DATA)
    target = MockConfigEntry(domain="parental", unique_id="pc1", data=DATA)
    other = MockConfigEntry(domain=DOMAIN, unique_id="pc2", data={**DATA, "device_id": "pc2"})
    mqtt_entry = MockConfigEntry(domain="mqtt", unique_id="broker", data={})
    for entry in (legacy, target, other, mqtt_entry):
        entry.add_to_hass(hass)

    devices, entities = dr.async_get(hass), er.async_get(hass)
    pc1_identifiers = {("mqtt", "smarthouse_gaming_pc1")}
    old_device = devices.async_get_or_create(config_entry_id=legacy.entry_id,
                                             identifiers=pc1_identifiers, name="Test PC 1")
    raw_device = devices.async_get_or_create(config_entry_id=mqtt_entry.entry_id,
                                             identifiers=pc1_identifiers, name="Test PC 1")
    other_device = devices.async_get_or_create(config_entry_id=other.entry_id,
                                               identifiers={("mqtt", "smarthouse_gaming_pc2")},
                                               name="Test PC 2")
    old_entity = entities.async_get_or_create("switch", DOMAIN, "pc1_unlimited",
                                              config_entry=legacy, device_id=old_device.id)
    raw_entity = entities.async_get_or_create("sensor", "mqtt", "smarthouse_gaming_pc1_current_game",
                                              config_entry=mqtt_entry, device_id=raw_device.id)
    other_entity = entities.async_get_or_create("switch", DOMAIN, "pc2_unlimited",
                                                config_entry=other, device_id=other_device.id)
    assert len({old_device.id, raw_device.id, other_device.id}) == 3
    await hass.async_block_till_done()

    entities.async_update_entity_platform(old_entity.entity_id, "parental",
                                          new_config_entry_id=target.entry_id)
    devices.async_update_device(old_device.id, new_config_entry_id=target.entry_id)
    await hass.async_block_till_done()
    moved = entities.async_get(old_entity.entity_id)
    assert moved.id == old_entity.id and moved.device_id == old_device.id
    assert moved.config_entry_id == target.entry_id and moved.platform == "parental"
    assert devices.async_get(old_device.id).config_entry_id == target.entry_id
    assert entities.async_get(raw_entity.entity_id) == raw_entity
    assert devices.async_get(raw_device.id) == raw_device
    assert entities.async_get(other_entity.entity_id) == other_entity
    assert devices.async_get(other_device.id) == other_device
    assert entities.async_get_entity_id("sensor", "mqtt", raw_entity.unique_id) == raw_entity.entity_id
    assert entities.async_get_entity_id("switch", DOMAIN, other_entity.unique_id) == other_entity.entity_id

    entities.async_update_entity_platform(old_entity.entity_id, DOMAIN,
                                          new_config_entry_id=legacy.entry_id)
    devices.async_update_device(old_device.id, new_config_entry_id=legacy.entry_id)
    await hass.async_block_till_done()
    assert entities.async_get(old_entity.entity_id).config_entry_id == legacy.entry_id
    assert devices.async_get(old_device.id).config_entry_id == legacy.entry_id
    assert entities.async_get(raw_entity.entity_id) == raw_entity
    assert entities.async_get(other_entity.entity_id) == other_entity


@pytest.mark.parametrize("reported,expected", [
    ("a" * 40, "a" * 40), ("abc", None), ("A" * 40, None), (True, None), (None, None),
])
async def test_agent_version_includes_validated_build_sha(hass, reported, expected):
    from unittest.mock import Mock
    from custom_components.smarthouse_gaming.agent_version import AgentVersionSensor
    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry.data = DATA
    entity = AgentVersionSensor(coordinator)
    entity.hass = hass
    with patch.object(entity, "async_write_ha_state"):
        entity._metadata(SimpleNamespace(topic="SmartHouse/Gaming/pc1/discovery",
            payload=json.dumps(DATA | {"agent_version": "0.2.2", "agent_build_sha": reported})))
        assert entity.native_value == "0.2.2"
        assert entity.extra_state_attributes["build_sha"] == expected
        entity._metadata(SimpleNamespace(topic="SmartHouse/Gaming/pc1/discovery",
            payload=json.dumps(DATA | {"agent_version": "0.2.1"})))
        assert entity.native_value == "0.2.1"
        assert entity.extra_state_attributes["build_sha"] is None


@pytest.mark.parametrize("info,expected", [
    ({"release":"Preview","component":"home_assistant","version":"0.5.0","commit":"b"*40}, "b"*40),
    ({"release":"Preview","component":"windows_agent","version":"0.5.0","commit":"b"*40}, None),
    ({"release":"Preview","component":"home_assistant","version":"0.4.3","commit":"b"*40}, None),
    ({"release":"Preview","component":"home_assistant","version":"0.5.0","commit":"bad"}, None),
    (None, None),
])
async def test_integration_version_reads_only_local_staged_provenance(hass, tmp_path, info, expected):
    from unittest.mock import AsyncMock, Mock
    from custom_components.smarthouse_gaming.entity import GamingEntity
    from custom_components.smarthouse_gaming.agent_version import IntegrationVersionSensor
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "0.5.0"}), encoding="utf-8")
    if info is not None:
        (tmp_path / "build-info.json").write_text(json.dumps(info), encoding="utf-8")
    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry.data = DATA
    entity = IntegrationVersionSensor(coordinator, root=tmp_path)
    entity.hass = hass
    with patch.object(GamingEntity, "async_added_to_hass", new_callable=AsyncMock), \
            patch.object(entity, "async_write_ha_state"):
        await entity.async_added_to_hass()
    assert entity.native_value == "0.5.0"
    assert entity.extra_state_attributes["build_sha"] == expected
    assert entity.available



@pytest.mark.parametrize("broker,port", [
    ("broker.example.invalid", 1883),
    ("mqtt.example.invalid", 8883),
    ("[::1]", 1883),
])
async def test_mqtt_info_shows_shared_broker_without_credentials(
        hass, enable_custom_integrations, broker, port):
    device_entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="pc1",
                                  options={"daily": 60})
    device_entry.add_to_hass(hass)
    manager = hass.config_entries.options
    result = await manager.async_init(device_entry.entry_id)
    with patch.object(cf.mqtt, "is_connected", return_value=True), \
            patch.object(cf, "_mqtt_broker_details", return_value=(broker, str(port)), create=True):
        result = await manager.async_configure(result["flow_id"],
                                              {"next_step_id": "mqtt_settings"})
    assert result["step_id"] == "mqtt_settings"
    assert result["description_placeholders"]["broker"] == broker
    assert result["description_placeholders"]["port"] == str(port)
    assert result["description_placeholders"]["root"] == "SmartHouse/Gaming/pc1"
    assert not result["data_schema"].schema
    assert "DO_NOT_DISPLAY_USER" not in repr(result)
    assert "DO_NOT_DISPLAY_PASSWORD" not in repr(result)
    await manager.async_configure(result["flow_id"], {})
    assert device_entry.options == {"daily": 60}
    from types import SimpleNamespace
    configured = SimpleNamespace(data={
        "broker": broker, "port": port, "username": "DO_NOT_DISPLAY_USER",
        "password": "DO_NOT_DISPLAY_PASSWORD"})
    fake_hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_entries=lambda domain: [configured] if domain == "mqtt" else []))
    assert cf._mqtt_broker_details(fake_hass) == (broker, str(port))


@pytest.mark.parametrize("value", ["user:password@broker.example", "broker.example/path", "", "x" * 260])
async def test_mqtt_info_does_not_echo_unexpected_broker_values(value):
    from types import SimpleNamespace
    configured = SimpleNamespace(data={
        "broker": value, "port": 1883, "password": "SECRET"})
    fake_hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_entries=lambda domain: [configured] if domain == "mqtt" else []))
    assert cf._mqtt_broker_details(fake_hass) == ("Not available", "1883")
