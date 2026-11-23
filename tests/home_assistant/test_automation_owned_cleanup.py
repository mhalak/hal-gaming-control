"""Regression contract for removing obsolete action selectors and hidden enforcement."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hal_gaming_control import _remove_legacy_statistics
from custom_components.hal_gaming_control.const import DOMAIN
from custom_components.hal_gaming_control.coordinator import GamingCoordinator

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

DATA = {"device_id": "pc1", "name": "Test PC", "protocol_version": 1,
        "games": ["Roblox"], "actions": ["terminate_game", "lock_pc"]}


@pytest.mark.parametrize("actions", [[], ["lock_pc"], ["lock_pc", "terminate_game"]])
async def test_options_menu_has_no_legacy_action_editors(hass, enable_custom_integrations, actions):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="pc1",
                            options={"actions": actions, "daily": 60})
    entry.add_to_hass(hass)
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["menu_options"] == {"mqtt_settings": "MQTT configuration",
                                       "tracked_apps": "Tracked applications",
                                       "windows_updates": "Windows updates (advanced)",
                                       }
    assert not {"add_action", "remove_action", "move_action"} & set(result["menu_options"])
    # Opening Configure and saving an unchanged HA app list must not erase
    # the stored actions or limits; no automatic action is triggered.
    with patch("custom_components.hal_gaming_control.config_flow._discover_foreground_candidate",
               new=AsyncMock(return_value=None)):
        form = await manager.async_configure(
            result["flow_id"], {"next_step_id": "tracked_apps"})
    saved = await manager.async_configure(form["flow_id"], {"applications": []})
    assert saved["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert saved["data"]["actions"] == actions
    assert saved["data"]["daily"] == 60


async def test_cleanup_retires_only_owned_action_selectors(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="pc1")
    entry.add_to_hass(hass)
    other = MockConfigEntry(domain=DOMAIN, data=DATA | {"device_id": "pc2"}, unique_id="pc2")
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    def create(domain, platform, key, owner):
        return registry.async_get_or_create(domain, platform, key, config_entry=owner).entity_id
    remove = [create("select", DOMAIN, "pc1_" + key, entry)
              for key in ("add_action", "remove_action")]
    keep = [create("button", DOMAIN, "pc1_lock_pc", entry),
            create("button", DOMAIN, "pc1_terminate_game", entry),
            create("sensor", DOMAIN, "pc1_active_game", entry),
            create("select", DOMAIN, "pc2_add_action", other),
            create("select", DOMAIN, "pc1_custom_selector", entry)]
    _remove_legacy_statistics(hass, entry)
    assert all(registry.async_get(entity_id) is not None for entity_id in keep)
    assert all(registry.async_get(entity_id) is None for entity_id in remove)


@pytest.mark.parametrize("direct", [False, True])
async def test_legacy_configured_actions_never_publish_automatically(hass, direct):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="pc1", options={
        "enabled": True, "daily": 0, "actions": ["terminate_game", "lock_pc"]})
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode", return_value=direct):
        c = GamingCoordinator(hass, entry)
    # Historical scalar entities are no longer an authoritative fallback.
    hass.states.async_set("sensor.test_game", "Roblox")
    hass.states.async_set("binary_sensor.test_in_game", "on")
    hass.states.async_set("sensor.test_uptime", "500")
    with patch("homeassistant.components.mqtt.async_publish",
               new_callable=AsyncMock) as publish:
        data = await c._async_update_data()
    assert data == {"ready": False, "online": False}
    publish.assert_not_awaited()
