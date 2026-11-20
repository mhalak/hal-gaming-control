"""Read-only migration preflight against real HA entries and registry."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthouse_gaming.const import DOMAIN

pytestmark = pytest.mark.asyncio

DATA = {"device_id": "pc1", "name": "Test PC", "protocol_version": 1,
        "games": ["Game"], "actions": ["lock_pc"]}


async def preflight(hass, entry):
    from custom_components.smarthouse_gaming.migration_preflight import async_preflight
    return await async_preflight(hass, entry)


@pytest.fixture
def source(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="pc1", data=DATA,
                            options={"enabled": True, "daily": 60, "bonus_minutes": 30})
    entry.add_to_hass(hass)
    return entry


async def test_clean_preflight_leaves_entry_and_registry_untouched(hass, source):
    registry = er.async_get(hass)
    entity = registry.async_get_or_create("sensor", DOMAIN, "pc1_current_game",
                                          config_entry=source)
    data, options = dict(source.data), dict(source.options)
    assert await preflight(hass, source) == ()
    assert dict(source.data) == data and dict(source.options) == options
    assert source.state is ConfigEntryState.NOT_LOADED
    assert hass.config_entries.async_get_entry(source.entry_id) is source
    assert hass.config_entries.async_entries("parental") == []
    assert registry.async_get(entity.entity_id) == entity


@pytest.mark.parametrize("domain, unique_id, device_id", [
    ("parental", "pc1", "pc1"), ("parental", "different", "pc1"),
    ("parental", "pc1", "different"), (DOMAIN, "different", "pc1"),
])
async def test_duplicate_device_blocks_migration(hass, source, domain, unique_id, device_id):
    other = MockConfigEntry(domain=domain, unique_id=unique_id,
                            data={**DATA, "device_id": device_id})
    other.add_to_hass(hass)
    assert "duplicate_device" in await preflight(hass, source)
    assert len(hass.config_entries.async_entries(domain)) == (2 if domain == DOMAIN else 1)


async def test_other_device_is_not_a_conflict(hass, source):
    MockConfigEntry(domain="parental", unique_id="pc2",
                    data={**DATA, "device_id": "pc2"}).add_to_hass(hass)
    assert await preflight(hass, source) == ()


@pytest.mark.parametrize("change, expected", [
    ({"version": 2}, "unsupported_entry"),
    ({"unique_id": "different"}, "invalid_identity"),
    ({"data": {**DATA, "protocol_version": 2}}, "invalid_identity"),
    ({"data": {**DATA, "device_id": "bad/id"}}, "invalid_identity"),
])
async def test_incompatible_source_rejected(hass, change, expected):
    kwargs = {"domain": DOMAIN, "unique_id": "pc1", "data": DATA, **change}
    entry = MockConfigEntry(**kwargs)
    entry.add_to_hass(hass)
    assert expected in await preflight(hass, entry)


async def test_unknown_and_wrong_domain_source_rejected(hass):
    absent = MockConfigEntry(domain=DOMAIN, unique_id="pc1", data=DATA)
    wrong = MockConfigEntry(domain="parental", unique_id="pc1", data=DATA)
    wrong.add_to_hass(hass)
    assert "unsupported_entry" in await preflight(hass, absent)
    assert "unsupported_entry" in await preflight(hass, wrong)


async def test_loaded_source_rejected(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="pc1", data=DATA,
                            state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    assert "source_not_unloaded" in await preflight(hass, entry)


async def test_destination_entity_identity_collision(hass, source):
    registry = er.async_get(hass)
    old = registry.async_get_or_create("sensor", DOMAIN, "pc1_current_game", config_entry=source)
    target = MockConfigEntry(domain="parental", unique_id="pc2",
                            data={**DATA, "device_id": "pc2"})
    target.add_to_hass(hass)
    conflict = registry.async_get_or_create("sensor", "parental", old.unique_id, config_entry=target)
    assert "entity_conflict" in await preflight(hass, source)
    assert registry.async_get(old.entity_id) == old
    assert registry.async_get(conflict.entity_id) == conflict


@pytest.mark.parametrize("saved, expected", [
    ({"pending": None, "deadline": None, "result": "success"}, None),
    ({"pending": {"request_id": "synthetic"}, "deadline": 100}, "update_pending"),
    ({"pending": {}, "deadline": 100}, "update_pending"),
    (["invalid"], "update_state_invalid"),
])
async def test_saved_update_state_is_read_only(hass, source, saved, expected):
    store = Store(hass, 1, f"smarthouse_gaming.update.{source.entry_id}")
    path = Path(store.path)
    await hass.async_add_executor_job(path.parent.mkdir, 0o700, True, True)
    raw = json.dumps({"version": 1, "minor_version": 1, "key": store.key, "data": saved})
    await hass.async_add_executor_job(path.write_text, raw, "utf-8")
    result = await preflight(hass, source)
    assert result == () if expected is None else expected in result
    assert await hass.async_add_executor_job(path.read_text, "utf-8") == raw


async def test_update_storage_failure_blocks_migration(hass, source):
    with patch("custom_components.smarthouse_gaming.migration_preflight._read_update_state",
               side_effect=OSError("synthetic")):
        assert "update_state_unavailable" in await preflight(hass, source)


@pytest.mark.parametrize("raw", [
    "{broken json", "null", "{}", '{"version": 2, "data": {"pending": null}}',
    '{"version": 1, "minor_version": 2, "data": {"pending": null}}',
    '{"version": 1, "data": {}}',
])
async def test_corrupt_or_unsupported_storage_remains_byte_identical(hass, source, raw, tmp_path):
    path = tmp_path / "update-state.json"
    path.write_text(raw, encoding="utf-8")
    with patch("custom_components.smarthouse_gaming.migration_preflight._update_path",
               return_value=path):
        assert "update_state_invalid" in await preflight(hass, source)
    assert path.read_text(encoding="utf-8") == raw
    assert list(tmp_path.iterdir()) == [path]
