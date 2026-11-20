"""Isolated durable migration journal. Never initiates registry mutations."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re

from homeassistant.helpers.storage import Store

KEY = "smarthouse_gaming.domain_migration"
PLAN_KEYS = {"device_id", "source_entry_id", "target_entry_id", "entity_ids", "device_ids"}
NEXT = {
    "prepared": frozenset({"registry_moved", "rollback_required"}),
    "registry_moved": frozenset({"verified", "rollback_required"}),
    "verified": frozenset({"completed", "rollback_required"}),
    "rollback_required": frozenset({"rolled_back"}),
    "rolled_back": frozenset(),
    "completed": frozenset(),
}
TERMINAL = {"completed", "rolled_back"}
MAX_BYTES = 1024 * 1024


def _matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _valid_list(values, pattern):
    return (isinstance(values, list) and all(_matches(value, pattern) for value in values)
            and len(set(values)) == len(values))


def _validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS:
        raise ValueError("Invalid migration plan schema")
    if not _matches(plan["device_id"], r"[A-Za-z0-9_-]{1,64}"):
        raise ValueError("Invalid migration device identity")
    entry_ids = (plan["source_entry_id"], plan["target_entry_id"])
    if (not all(_matches(value, r"[A-Za-z0-9_-]{1,128}") for value in entry_ids)
            or entry_ids[0] == entry_ids[1]):
        raise ValueError("Invalid migration entry identities")
    if (not _valid_list(plan["entity_ids"], r"[a-z0-9_]+\.[a-z0-9_]+")
            or not _valid_list(plan["device_ids"], r"[A-Za-z0-9_-]{1,128}")):
        raise ValueError("Invalid migration registry inventory")


def _read_record(path):
    # Store.async_load may rename malformed files or automatically migrate them.
    # Read only our own envelope so corruption cannot look like an empty journal.
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(payload) > MAX_BYTES:
        raise ValueError("Migration journal exceeds size limit")
    raw = json.loads(payload)
    if (not isinstance(raw, dict) or type(raw.get("version")) is not int
            or raw["version"] != 1 or type(raw.get("minor_version", 1)) is not int
            or raw.get("minor_version", 1) != 1 or raw.get("key") != KEY):
        raise ValueError("Invalid migration journal envelope")
    record = raw.get("data")
    if (not isinstance(record, dict) or set(record) != {"stage", "plan"}
            or not isinstance(record["stage"], str) or record["stage"] not in NEXT):
        raise ValueError("Invalid migration journal record")
    _validate_plan(record["plan"])
    return record


class MigrationJournal:
    """One in-process serialized journal; recovery must reconcile actual registries."""

    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, KEY, private=True, atomic_writes=True)
        self.lock = hass.data.setdefault(KEY, asyncio.Lock())

    async def async_load(self):
        return await self.hass.async_add_executor_job(_read_record, Path(self.store.path))

    async def _save(self, record):
        await self.store.async_save(record)
        # Core can log an underlying write failure without propagating it.
        if await self.async_load() != record:
            raise OSError("Migration journal write not confirmed")

    async def async_prepare(self, plan):
        plan = deepcopy(plan)
        _validate_plan(plan)
        async with self.lock:
            if await self.async_load() is not None:
                raise ValueError("An outstanding migration must be reconciled first")
            await self._save({"stage": "prepared", "plan": plan})

    async def async_advance(self, expected_stage, next_stage):
        async with self.lock:
            record = await self.async_load()
            if (record is None or record["stage"] != expected_stage
                    or next_stage not in NEXT[record["stage"]]):
                raise ValueError("Invalid migration stage transition")
            await self._save({**record, "stage": next_stage})

    async def async_clear(self):
        async with self.lock:
            record = await self.async_load()
            if record is None or record["stage"] not in TERMINAL:
                raise ValueError("Cannot clear an unresolved migration")
            await self.store.async_remove()
            if await self.async_load() is not None:
                raise OSError("Migration journal removal not confirmed")
