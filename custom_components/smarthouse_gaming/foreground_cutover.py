"""Persist a per-entry foreground accounting epoch; no automatic activation."""
import asyncio
import json
from pathlib import Path
import re

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOCKS = f"{DOMAIN}.foreground_cutover_locks"
_MAX_TIMESTAMP = 253402300799


class CutoverError(RuntimeError):
    """Cutover identity, storage or timestamp cannot be trusted."""


def _store(hass, entry_id, device_id):
    if not all(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value)
               for value in (entry_id, device_id)):
        raise CutoverError("Invalid cutover identity")
    return Store(hass, 1, f"{DOMAIN}.foreground_cutover.{entry_id}")


def _timestamp(value):
    if type(value) not in (int, float) or not 0 <= value <= _MAX_TIMESTAMP:
        raise CutoverError("Invalid cutover timestamp")
    return float(value)


def _validate(payload, device_id):
    if not isinstance(payload, dict) or payload.get("device_id") != device_id:
        raise CutoverError("Invalid cutover device identity")
    return _timestamp(payload.get("since"))


def _check_envelope(path, key):
    # Store may rename corrupt files or migrate versions. Refuse such inputs
    # before calling it, preserving the original evidence for recovery.
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    if (not isinstance(raw, dict) or type(raw.get("version")) is not int
            or raw["version"] != 1 or type(raw.get("minor_version", 1)) is not int
            or raw.get("minor_version", 1) != 1 or raw.get("key") != key
            or not isinstance(raw.get("data"), dict)):
        raise CutoverError("Invalid cutover storage envelope")


async def _load(hass, store, device_id):
    try:
        await hass.async_add_executor_job(_check_envelope, Path(store.path), store.key)
        payload = await store.async_load()
    except (OSError, ValueError) as err:
        raise CutoverError("Cannot read cutover storage") from err
    return None if payload is None else _validate(payload, device_id)


def _lock(hass, entry_id):
    return hass.data.setdefault(_LOCKS, {}).setdefault(entry_id, asyncio.Lock())


async def async_read_cutover(hass, entry_id, device_id):
    """Read the saved epoch; None means not explicitly activated."""
    store = _store(hass, entry_id, device_id)
    async with _lock(hass, entry_id):
        return await _load(hass, store, device_id)


async def async_activate_cutover(hass, entry_id, device_id):
    """Create a durable epoch once, without changing any runtime accounting."""
    store = _store(hass, entry_id, device_id)
    async with _lock(hass, entry_id):
        existing = await _load(hass, store, device_id)
        if existing is not None:
            return existing
        since = _timestamp(dt_util.utcnow().timestamp())
        try:
            await store.async_save({"device_id": device_id, "since": since})
        except (OSError, ValueError) as err:
            raise CutoverError("Cannot save cutover storage") from err
        if await _load(hass, _store(hass, entry_id, device_id), device_id) != since:
            raise CutoverError("Cutover storage write could not be verified")
        return since
