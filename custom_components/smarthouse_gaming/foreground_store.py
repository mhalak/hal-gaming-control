"""Crash-consistent, per-config-entry confirmed foreground interval checkpoint.

The Home Assistant Store is separate from Recorder and stores only intervals
supported by two fresh ordered samples; it NEVER stores a live sample for
replay after restart. Missing storage means no confirmed history, not proof
that older usage was idle.
"""
import asyncio
import json
import math
import re

from homeassistant.helpers.storage import Store

from .app_registry import identity_key
from .const import DOMAIN
from .foreground_accounting import _validated_segments

MAX_SEGMENTS = 8192
MAX_TIMESTAMP = 253402300799


class ForegroundStoreError(ValueError):
    """Untrusted device/storage data must halt a cutover, never reset limits."""


def _time(value):
    if (type(value) not in (float, int) or not math.isfinite(value)
            or not 0 <= value <= MAX_TIMESTAMP):
        raise ForegroundStoreError("Invalid foreground checkpoint timestamp")
    return float(value)


def _stable_key(key):
    """Only validated canonical raw keys may be loaded as historic identities."""
    if not isinstance(key, str) or len(key) > 512:
        raise ForegroundStoreError("Invalid stored application identity")
    try:
        process, discriminator = json.loads(key)
        if discriminator is None:
            signature = None
        else:
            kind, value = discriminator
            signature = {"kind": kind, "value": value}
        if identity_key(process, signature) != key:
            raise ValueError("Noncanonical identity")
    except (ValueError, TypeError, KeyError, IndexError) as err:
        raise ForegroundStoreError("Invalid stored application identity") from err
    return key


def _segments(value, since):
    if not isinstance(value, list) or len(value) > MAX_SEGMENTS:
        raise ForegroundStoreError("Invalid foreground interval count")
    try:
        keys = {_stable_key(row[2]) for row in value}
        segments = _validated_segments(value, keys)
    except (ValueError, TypeError, IndexError, KeyError) as err:
        raise ForegroundStoreError("Invalid foreground intervals") from err
    if any(start < since or end > MAX_TIMESTAMP for start, end, _ in segments):
        raise ForegroundStoreError("Interval crosses the configured cutover")
    return tuple(segments)


def _payload(device_id, since, segments):
    if (not isinstance(device_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device_id) is None):
        raise ForegroundStoreError("Invalid device ID")
    epoch = _time(since)
    return {"version": 1, "device_id": device_id, "cutover_since": epoch,
            "segments": [list(row) for row in _segments(list(segments), epoch)]}


def validate_checkpoint(value, device_id, since):
    """Strict schema/identity/cutover validation; no silent data resetting."""
    if value is None:
        return ()
    if (not isinstance(value, dict)
            or value.keys() != {"version", "device_id", "cutover_since", "segments"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["device_id"] != device_id
            or _time(value["cutover_since"]) != _time(since)):
        raise ForegroundStoreError("Invalid foreground checkpoint metadata")
    return _segments(value["segments"], _time(since))


class ForegroundStore:
    """Durable per-entry checkpoints with serialized writes and strict reads."""

    def __init__(self, hass, entry_id, device_id):
        if (not isinstance(entry_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", entry_id) is None):
            raise ForegroundStoreError("Invalid config entry ID")
        _payload(device_id, 0, ())
        self.device_id = device_id
        self.storage = Store(hass, 1, f"{DOMAIN}.foreground_segments.{entry_id}")
        self._lock = asyncio.Lock()

    async def async_load(self, since):
        async with self._lock:
            try:
                payload = await self.storage.async_load()
            except (OSError, ValueError, TypeError) as err:
                raise ForegroundStoreError("Cannot load foreground checkpoint") from err
            return validate_checkpoint(payload, self.device_id, since)

    async def async_save(self, since, segments):
        payload = _payload(self.device_id, since, segments)
        async with self._lock:
            try:
                await self.storage.async_save(payload)
            except (OSError, ValueError, TypeError) as err:
                raise ForegroundStoreError("Cannot save foreground checkpoint") from err
