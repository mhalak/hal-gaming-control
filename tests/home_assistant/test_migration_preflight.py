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


async def test_preflight_accepts_one_owned_device_and_independent_native_mqtt(hass, source):
    from homeassistant.helpers import device_registry as dr

    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    mqtt_entry = MockConfigEntry(domain="mqtt", unique_id="broker", data={})
    mqtt_entry.add_to_hass(hass)
    identifiers = {("mqtt", "smarthouse_gaming_pc1")}
    owned = devices.async_get_or_create(config_entry_id=source.entry_id,
                                        identifiers=identifiers, name="PC")
    raw = devices.async_get_or_create(config_entry_id=mqtt_entry.entry_id,
                                      identifiers=identifiers, name="PC")
    entity = registry.async_get_or_create("sensor", DOMAIN, "pc1_current_game",
                                          config_entry=source, device_id=owned.id)
    native = registry.async_get_or_create("sensor", "mqtt", "smarthouse_gaming_pc1_current_game",
                                          config_entry=mqtt_entry, device_id=raw.id)
    assert await preflight(hass, source) == ()
    assert devices.async_get(owned.id).config_entry_id == source.entry_id
    assert devices.async_get(raw.id).config_entry_id == mqtt_entry.entry_id
    assert registry.async_get(entity.entity_id) == entity
    assert registry.async_get(native.entity_id) == native


@pytest.mark.parametrize("identifiers", [
    {("mqtt", "smarthouse_gaming_pc2")},
    {("mqtt", "smarthouse_gaming_pc1"), ("unrelated", "unknown")},
])
async def test_preflight_rejects_unexpected_owned_device_identity(hass, source, identifiers):
    from homeassistant.helpers import device_registry as dr

    devices = dr.async_get(hass)
    device = devices.async_get_or_create(config_entry_id=source.entry_id,
                                         identifiers=identifiers, name="Unexpected")
    assert "device_ownership_conflict" in await preflight(hass, source)
    assert devices.async_get(device.id) == device


async def test_preflight_rejects_multiple_owned_devices(hass, source):
    from homeassistant.helpers import device_registry as dr

    devices = dr.async_get(hass)
    first = devices.async_get_or_create(config_entry_id=source.entry_id,
                                        identifiers={("mqtt", "smarthouse_gaming_pc1")})
    second = devices.async_get_or_create(config_entry_id=source.entry_id,
                                         identifiers={("mqtt", "smarthouse_gaming_unexpected")})
    assert "device_ownership_conflict" in await preflight(hass, source)
    assert devices.async_get(first.id) == first
    assert devices.async_get(second.id) == second


async def test_preflight_rejects_other_pc_entity_in_legacy_entry(hass, source):
    registry = er.async_get(hass)
    entity = registry.async_get_or_create("sensor", DOMAIN, "pc2_current_game",
                                          config_entry=source)
    assert "entity_ownership_conflict" in await preflight(hass, source)
    assert registry.async_get(entity.entity_id) == entity


async def test_preflight_rejects_unsupported_minor_version(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="pc1", data=DATA, minor_version=2)
    entry.add_to_hass(hass)
    assert "unsupported_entry" in await preflight(hass, entry)


async def test_preflight_rejects_entity_link_to_native_mqtt_device(hass, source):
    from homeassistant.helpers import device_registry as dr

    # HA permits a foreign device reference for an existing registry record.
    # Such a link cannot be safely transferred as an owned device.
    mqtt_entry = MockConfigEntry(domain="mqtt", unique_id="broker", data={})
    mqtt_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    native = devices.async_get_or_create(config_entry_id=mqtt_entry.entry_id,
                                          identifiers={("mqtt", "smarthouse_gaming_pc1")})
    registry = er.async_get(hass)
    # Test the fail-closed inventory check even on HA versions which prevent
    # constructing a foreign device link via their registry writer.
    entity = registry.async_get_or_create("sensor", DOMAIN, "pc1_current_game", config_entry=source)
    from types import SimpleNamespace
    foreign = SimpleNamespace(platform=DOMAIN, unique_id=entity.unique_id,
                              config_subentry_id=None, device_id=native.id,
                              domain=entity.domain)
    with patch.object(er, "async_entries_for_config_entry", return_value=[foreign]):
        assert "entity_ownership_conflict" in await preflight(hass, source)
    assert registry.async_get(entity.entity_id) == entity
    assert devices.async_get(native.id) == native


# Issue #5: an integration domain is not an editable config-entry option.
# A migration may never assume that replacing a package directory rewrites
# existing HA entries, nor may it attempt private .storage edits.
async def test_config_entry_domain_is_immutable_in_public_ha_api(hass, source):
    original_id, original_domain = source.entry_id, source.domain
    with pytest.raises(AttributeError):
        source.domain = "parental"
    with pytest.raises(TypeError):
        hass.config_entries.async_update_entry(source, domain="parental")
    assert source.entry_id == original_id
    assert source.domain == original_domain
    assert hass.config_entries.async_entries("parental") == []


async def test_read_only_domain_migration_inventory_preserves_all_options(hass, source):
    from homeassistant.helpers import device_registry as dr
    from custom_components.smarthouse_gaming.domain_migration_inventory import (
        async_inventory,
    )

    # Full HA options are preserved exactly, not a reconstructed defaults
    # object that loses a parent-configured tracked app or future setting.
    source_options = {
        "enabled": True, "daily": 180, "weekly": 4200,
        "schedule_enabled": True, "schedule_start": "16:00",
        "schedule_end": "20:00", "weekend_schedule_start": "10:00",
        "weekend_schedule_end": "22:00",
        "weekend_bonus": 60, "bonus_date": "2026-11-22",
        "bonus_minutes": 30,
        "tracked_apps": [{"process": "RobloxPlayerBeta.exe", "signature": None,
                          "name": "Roblox"}],
        "update_catalog_url": "https://example.invalid/catalog",
    }
    hass.config_entries.async_update_entry(source, options=source_options)
    devices = dr.async_get(hass)
    owned = devices.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "smarthouse_gaming_pc1")}, name="Test PC")
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor", DOMAIN, "pc1_active_game",
        config_entry=source, device_id=owned.id)
    original_entity = registry.async_get(entity.entity_id)
    report = await async_inventory(hass, source)
    assert report == {
        "source_domain": DOMAIN,
        "target_domain": "parental",
        "source_entry_id": source.entry_id,
        "device_id": "pc1",
        "unique_id": source.unique_id,
        "title": source.title,
        "data": dict(source.data),
        "options": source_options,
        "entity_ids": (entity.entity_id,),
        "device_ids": (owned.id,),
        "updater_store_key": f"smarthouse_gaming.update.{source.entry_id}",
    }
    # Private data/option snapshots are in memory only and must be copies.
    assert report["options"] is not source.options
    report["options"]["tracked_apps"][0]["name"] = "Changed in report"
    assert source.options["tracked_apps"][0]["name"] == "Roblox"
    assert registry.async_get(entity.entity_id) == original_entity
    assert hass.config_entries.async_get_entry(source.entry_id) is source
    assert hass.config_entries.async_entries("parental") == []


async def test_domain_migration_inventory_blocks_loaded_source_or_duplicate(hass, source):
    from custom_components.smarthouse_gaming.domain_migration_inventory import (
        MigrationBlocked, async_inventory,
    )

    duplicated = MockConfigEntry(
        domain="parental", unique_id="pc1",
        data={**DATA, "device_id": "pc1"})
    duplicated.add_to_hass(hass)
    with pytest.raises(MigrationBlocked) as blocked:
        await async_inventory(hass, source)
    assert blocked.value.reasons == ("duplicate_device",)
    assert hass.config_entries.async_entries("parental") == [duplicated]

    # If a source is loaded, transfer would race live subscriptions/commands.
    entry = MockConfigEntry(domain=DOMAIN, unique_id="pc2",
                            data={**DATA, "device_id": "pc2"},
                            state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    with pytest.raises(MigrationBlocked) as blocked:
        await async_inventory(hass, entry)
    assert blocked.value.reasons == ("source_not_unloaded",)


async def test_domain_migration_inventory_fails_closed_on_pending_updater(hass, source):
    from custom_components.smarthouse_gaming.domain_migration_inventory import (
        MigrationBlocked, async_inventory,
    )
    store = Store(hass, 1, f"smarthouse_gaming.update.{source.entry_id}")
    path = Path(store.path)
    await hass.async_add_executor_job(path.parent.mkdir, 0o700, True, True)
    raw = json.dumps({"version": 1, "minor_version": 1, "key": store.key,
                      "data": {"pending": {"request_id": "synthetic"}}})
    await hass.async_add_executor_job(path.write_text, raw, "utf-8")
    with pytest.raises(MigrationBlocked) as blocked:
        await async_inventory(hass, source)
    assert blocked.value.reasons == ("update_pending",)
    assert await hass.async_add_executor_job(path.read_text, "utf-8") == raw
