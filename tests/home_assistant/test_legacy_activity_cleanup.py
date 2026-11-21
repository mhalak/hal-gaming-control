"""Gated native/scoped entity cleanup never deletes history or other devices."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import mqtt
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming.const import DOMAIN
from custom_components.smarthouse_gaming.legacy_activity_cleanup import (
    RetirementBlocked, async_retire, exact_legacy_topics, owned_direct_entities,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]


def config_entry(hass, device):
    entry = MockConfigEntry(
        domain=DOMAIN, title=device,
        data={"device_id": device, "name": device, "games": [], "actions": []},
        unique_id=device)
    entry.add_to_hass(hass)
    return entry


def registered(hass, entry, key, domain="sensor", platform=DOMAIN):
    uid = (f"{entry.data['device_id']}_{key}" if platform == DOMAIN
           else f"smarthouse_gaming_{entry.data['device_id']}_{key}")
    return er.async_get(hass).async_get_or_create(
        domain, platform, uid,
        config_entry=entry if platform == DOMAIN else None,
        suggested_object_id=uid)


async def test_exact_topics_have_no_wildcards_or_other_device():
    expected = (
        "homeassistant/sensor/smarthouse_gaming_pc1_current_game/config",
        "homeassistant/binary_sensor/smarthouse_gaming_pc1_in_game/config",
        "homeassistant/binary_sensor/smarthouse_gaming_pc1_gaming_active/config",
        "homeassistant/sensor/smarthouse_gaming_pc1_active_game/config",
    )
    assert exact_legacy_topics("pc1") == expected
    assert exact_legacy_topics("pc2") != expected
    assert all("+" not in x and "#" not in x for x in expected)


@pytest.mark.parametrize("device,prefix", [
    ("pc/1", "homeassistant"),
    ("+", "homeassistant"),
    ("pc1", "homeassistant/#"),
    ("pc1", "../homeassistant"),
    ("pc1", ""),
])
async def test_untrusted_topic_scope_is_rejected(device, prefix):
    with pytest.raises(RetirementBlocked):
        exact_legacy_topics(device, prefix)


async def test_cleanup_defaults_to_blocked_and_keeps_entities(hass):
    entry = config_entry(hass, "pc1")
    old = registered(hass, entry, "current_game")
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as pub:
        with pytest.raises(RetirementBlocked):
            await async_retire(hass, entry, v2_cutover_verified=False,
                               legacy_discovery_stopped=False)
    pub.assert_not_called()
    assert er.async_get(hass).async_get(old.entity_id) is not None


async def test_exact_scoped_registry_cleanup_preserves_unrelated_entries(hass):
    entry1 = config_entry(hass, "pc1")
    entry2 = config_entry(hass, "pc2")
    one = [
        registered(hass, entry1, "current_game"),
        registered(hass, entry1, "in_game", "binary_sensor"),
        registered(hass, entry1, "gaming_active", "binary_sensor"),
    ]
    keep = [
        registered(hass, entry1, "active_game"),
        registered(hass, entry1, "uptime"),
        registered(hass, entry2, "current_game"),
    ]
    registry = er.async_get(hass)
    assert owned_direct_entities(
        er.async_entries_for_config_entry(registry, entry1.entry_id),
        entry1.entry_id, "pc1") == tuple(e.entity_id for e in one)
    with patch.object(mqtt, "is_connected", return_value=True), \
            patch.object(mqtt, "async_publish", new_callable=AsyncMock) as pub:
        done = await async_retire(hass, entry1, v2_cutover_verified=True,
                                  legacy_discovery_stopped=True)
    assert pub.await_count == 4
    assert set(done["retired_scoped"]) == {e.entity_id for e in one}
    for old in one:
        assert registry.async_get(old.entity_id) is None
    for entity in keep:
        assert registry.async_get(entity.entity_id) is not None


async def test_broker_disconnect_blocks_all_mutations(hass):
    entry = config_entry(hass, "pc1")
    old = registered(hass, entry, "current_game")
    with patch.object(mqtt, "is_connected", return_value=False), \
            patch.object(mqtt, "async_publish", new_callable=AsyncMock) as pub:
        with pytest.raises(RetirementBlocked):
            await async_retire(hass, entry, v2_cutover_verified=True,
                               legacy_discovery_stopped=True)
    pub.assert_not_called()
    assert er.async_get(hass).async_get(old.entity_id) is not None
