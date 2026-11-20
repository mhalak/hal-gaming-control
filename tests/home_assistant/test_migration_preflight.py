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


# Journal state is independent of live registry mutation. A prepared record
# survives object recreation, and is never overwritten by another migration.
def journal(hass):
    from custom_components.smarthouse_gaming.migration_journal import MigrationJournal
    return MigrationJournal(hass)


def transfer_plan():
    return {
        "device_id": "pc1",
        "source_entry_id": "synthetic-source",
        "target_entry_id": "synthetic-target",
        "entity_ids": ["sensor.pc1_current_game", "switch.pc1_unlimited"],
        "device_ids": ["synthetic-device"],
    }


async def test_migration_journal_persists_prepare_before_registry_mutation(hass):
    plan = transfer_plan()
    j = journal(hass)
    assert await j.async_load() is None
    await j.async_prepare(plan)
    plan["entity_ids"].clear()
    restored = await journal(hass).async_load()
    assert restored == {"stage": "prepared", "plan": transfer_plan()}
    # Preparation cannot create an entry or change registry ownership.
    assert hass.config_entries.async_entries("parental") == []
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_migration_journal_refuses_second_transaction(hass):
    j = journal(hass)
    await j.async_prepare(transfer_plan())
    other = {**transfer_plan(), "device_id": "pc2"}
    with pytest.raises(ValueError):
        await journal(hass).async_prepare(other)
    assert await j.async_load() == {"stage": "prepared", "plan": transfer_plan()}


async def test_migration_journal_legal_forward_transitions_survive_recreation(hass):
    await journal(hass).async_prepare(transfer_plan())
    for before, after in [("prepared", "registry_moved"), ("registry_moved", "verified"),
                          ("verified", "completed")]:
        j = journal(hass)
        await j.async_advance(before, after)
        assert await journal(hass).async_load() == {"stage": after, "plan": transfer_plan()}
    await journal(hass).async_clear()
    assert await journal(hass).async_load() is None


@pytest.mark.parametrize("expected,next_stage", [
    ("registry_moved", "verified"), ("prepared", "completed"),
    ("prepared", "prepared"), ("prepared", "unknown"),
])
async def test_migration_journal_rejects_wrong_or_skipped_transition(hass, expected, next_stage):
    await journal(hass).async_prepare(transfer_plan())
    with pytest.raises(ValueError):
        await journal(hass).async_advance(expected, next_stage)
    assert await journal(hass).async_load() == {"stage": "prepared", "plan": transfer_plan()}


@pytest.mark.parametrize("current", ["prepared", "registry_moved", "verified"])
async def test_migration_journal_supports_explicit_recovery_without_losing_plan(hass, current):
    j = journal(hass)
    await j.async_prepare(transfer_plan())
    if current in ("registry_moved", "verified"):
        await j.async_advance("prepared", "registry_moved")
    if current == "verified":
        await j.async_advance("registry_moved", "verified")
    with pytest.raises(ValueError):
        await journal(hass).async_clear()
    await journal(hass).async_advance(current, "rollback_required")
    assert await journal(hass).async_load() == {"stage": "rollback_required", "plan": transfer_plan()}
    with pytest.raises(ValueError):
        await journal(hass).async_clear()
    await journal(hass).async_advance("rollback_required", "rolled_back")
    await journal(hass).async_clear()
    assert await journal(hass).async_load() is None


@pytest.mark.parametrize("changes", [
    {"device_id": "bad/id"},
    {"source_entry_id": ""},
    {"target_entry_id": "synthetic-source"},
    {"entity_ids": ["sensor.pc1_current_game", "sensor.pc1_current_game"]},
    {"device_ids": ["same", "same"]},
    {"entity_ids": ["not-an-entity-id"]},
    {"unexpected": "not part of the schema"},
])
async def test_migration_journal_rejects_invalid_plan(hass, changes):
    j = journal(hass)
    with pytest.raises(ValueError):
        await j.async_prepare(transfer_plan() | changes)
    assert await j.async_load() is None


async def test_migration_journal_requires_record_before_advancing_or_clearing(hass):
    j = journal(hass)
    with pytest.raises(ValueError):
        await j.async_advance("prepared", "registry_moved")
    with pytest.raises(ValueError):
        await j.async_clear()
    assert await j.async_load() is None
