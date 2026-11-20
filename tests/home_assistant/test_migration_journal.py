"""Durable migration journal tests using real temporary filesystem writes.

Home Assistant's default hass_storage fixture intercepts Store.async_save in
memory. Override it here because journal correctness requires checking persisted
on-disk bytes after each write, and confirming corrupt bytes fail closed.
"""
from unittest.mock import patch
import pytest

from custom_components.smarthouse_gaming.const import DOMAIN

pytestmark = pytest.mark.asyncio


@pytest.fixture
def hass_config_dir(tmp_path):
    """Use an isolated configuration directory for every on-disk journal test."""
    return str(tmp_path)


@pytest.fixture
def hass_storage():
    """Disable mock_storage only for these durable Store integration tests."""
    return {}


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


async def test_migration_journal_corruption_is_not_treated_as_absence(hass):
    from pathlib import Path

    j = journal(hass)
    await j.async_prepare(transfer_plan())
    path = Path(j.store.path)
    raw = b"{broken journal"
    await hass.async_add_executor_job(path.write_bytes, raw)
    with pytest.raises(ValueError):
        await j.async_load()
    with pytest.raises(ValueError):
        await j.async_prepare(transfer_plan())
    assert await hass.async_add_executor_job(path.read_bytes) == raw


async def test_migration_journal_rejects_unconfirmed_write(hass):
    from unittest.mock import AsyncMock

    j = journal(hass)
    with patch.object(j.store, "async_save", new_callable=AsyncMock):
        with pytest.raises(OSError, match="write not confirmed"):
            await j.async_prepare(transfer_plan())
    assert await journal(hass).async_load() is None


async def test_migration_journal_shared_lock_prevents_concurrent_prepare(hass):
    import asyncio

    first = transfer_plan()
    second = {**transfer_plan(), "device_id": "pc2"}
    results = await asyncio.gather(journal(hass).async_prepare(first),
                                   journal(hass).async_prepare(second),
                                   return_exceptions=True)
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert sum(result is None for result in results) == 1
    assert (await journal(hass).async_load())["plan"] in (first, second)


async def test_migration_journal_rejects_unconfirmed_removal(hass):
    from unittest.mock import AsyncMock

    j = journal(hass)
    await j.async_prepare(transfer_plan())
    await j.async_advance("prepared", "rollback_required")
    await j.async_advance("rollback_required", "rolled_back")
    with patch.object(j.store, "async_remove", new_callable=AsyncMock):
        with pytest.raises(OSError, match="removal not confirmed"):
            await j.async_clear()
    assert (await journal(hass).async_load())["stage"] == "rolled_back"


@pytest.mark.parametrize("change", [
    {"version": 2},
    {"minor_version": 2},
    {"key": "foreign"},
    {"data": {"stage": "unknown", "plan": transfer_plan()}},
    {"data": {"stage": [], "plan": transfer_plan()}},
    {"data": {"stage": "prepared", "plan": {}}},
])
async def test_migration_journal_invalid_envelope_fails_closed(hass, change):
    import json
    from pathlib import Path
    from custom_components.smarthouse_gaming.migration_journal import KEY

    j = journal(hass)
    await j.async_prepare(transfer_plan())
    path = Path(j.store.path)
    payload = json.dumps({"version": 1, "minor_version": 1, "key": KEY,
                          "data": {"stage": "prepared", "plan": transfer_plan()}} | change)
    await hass.async_add_executor_job(path.write_text, payload, "utf-8")
    with pytest.raises(ValueError):
        await j.async_load()
    assert await hass.async_add_executor_job(path.read_text, "utf-8") == payload


async def test_migration_journal_excessive_size_is_rejected(hass):
    from pathlib import Path
    from custom_components.smarthouse_gaming.migration_journal import MAX_BYTES

    j = journal(hass)
    await j.async_prepare(transfer_plan())
    path = Path(j.store.path)
    await hass.async_add_executor_job(path.write_bytes, b" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="size limit"):
        await j.async_load()
