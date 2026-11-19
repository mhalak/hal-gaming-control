"""Optional standard HA update entity. Administrative, not a gaming action."""
import asyncio
import json
import logging
from datetime import timedelta
from time import monotonic, time

from aiohttp import ClientTimeout, ClientError
from homeassistant.components import mqtt
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import ROOT
from .entity import GamingEntity
from .protocol import parse_discovery
from .update_protocol import ACTIVE, TERMINAL, catalog_url, catalog_version, make_request, parse_status, version_tuple

_LOGGER = logging.getLogger(__name__)
TIMEOUT = 20 * 60

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([WindowsAgentUpdate(entry.runtime_data)])

class WindowsAgentUpdate(GamingEntity, UpdateEntity):
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_title = "SmartHouse Windows Agent"
    _attr_auto_update = False

    def __init__(self, coordinator):
        super().__init__(coordinator, "agent_update", "Windows agent update")
        self.root = f"{ROOT}/{coordinator.device_id}"
        self.installed = None
        self.approved = None
        self.capable = False
        self.pending = None
        self.started = None
        self.result = None
        self.last_catalog = float("-inf")
        self.lock = asyncio.Lock()
        self.store = None
        self.deadline = None

    @property
    def installed_version(self):
        return self.installed

    @property
    def latest_version(self):
        if self.installed and self.approved and version_tuple(self.approved) < version_tuple(self.installed):
            return self.installed
        return self.approved

    @property
    def available(self):
        return bool(self.pending or (self.capable and self.installed and self.approved and
                    self.coordinator.data.get("online")))

    @property
    def in_progress(self):
        return self.pending is not None

    @property
    def extra_state_attributes(self):
        return {"update_status": self.result, "request_id": self.pending["request_id"] if self.pending else None}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.store = Store(self.hass, 1, f"smarthouse_gaming.update.{self.coordinator.entry.entry_id}")
        saved = await self.store.async_load()
        if saved:
            self._restore(saved)
        self.async_on_remove(await mqtt.async_subscribe(self.hass, self.root + "/discovery", self._metadata, qos=1))
        self.async_on_remove(await mqtt.async_subscribe(self.hass, self.root + "/update/status", self._status, qos=1))
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, timedelta(seconds=30)))
        await self._refresh_catalog()

    def _snapshot(self):
        return {"pending": self.pending, "deadline": self.deadline, "result": self.result}

    def _restore(self, saved):
        if not isinstance(saved, dict):
            return
        self.result = saved.get("result")
        pending, deadline = saved.get("pending"), saved.get("deadline")
        if not pending:
            return
        try:
            parse_status(json.dumps({"status": "starting", "version": pending["version"],
                                     "request_id": pending["request_id"], "timestamp": 0}))
            if type(deadline) not in (int, float) or not time() < deadline <= time() + TIMEOUT:
                raise ValueError("Expired update tracking")
        except (ValueError, TypeError, KeyError):
            self.result = "timeout_unconfirmed"
            return
        self.pending, self.deadline = pending, deadline
        self.started = monotonic() - (TIMEOUT - (deadline - time()))

    @callback
    def _save_later(self):
        if self.store is not None:
            self.store.async_delay_save(self._snapshot, 1)

    async def async_will_remove_from_hass(self):
        if self.store is not None:
            await self.store.async_save(self._snapshot())
        await super().async_will_remove_from_hass()

    @callback
    def _metadata(self, message):
        try:
            parse_discovery(message.topic, message.payload)
            raw = json.loads(message.payload)
            version_tuple(raw["agent_version"])
            self.installed = raw["agent_version"]
            self.capable = raw.get("remote_update") is True
        except (KeyError, ValueError, TypeError):
            self.capable = False
            self.installed = None
        self._complete()
        self.async_write_ha_state()

    @callback
    def _status(self, message):
        try:
            value = parse_status(message.payload)
        except (ValueError, TypeError):
            return
        if not self.pending or value["request_id"] != self.pending["request_id"] or value["version"] != self.pending["version"]:
            return
        state = value["status"]
        if self.result in TERMINAL:
            return
        self.result = state
        self._complete()
        self._save_later()
        self.async_write_ha_state()

    @callback
    def _complete(self):
        if self.pending and (self.result in TERMINAL - {"success"} or
              (self.result == "success" and self.installed == self.pending["version"])):
            self.pending = None
            self.started = None
            self.deadline = None
            self._save_later()

    async def _refresh_catalog(self):
        self.last_catalog = monotonic()
        value = self.coordinator.entry.options.get("update_catalog_url", "")
        if not value:
            self.approved = None
            return
        try:
            url = catalog_url(value)
            session = async_get_clientsession(self.hass)
            async with session.get(url, timeout=ClientTimeout(total=10), allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError("Catalog HTTP status")
                # Read at most 4097 bytes, reject oversized catalogs.
                raw = bytearray()
                async for chunk in response.content.iter_chunked(1024):
                    raw.extend(chunk)
                    if len(raw) > 4096:
                        raise ValueError("Catalog size limit")
            self.approved = catalog_version(bytes(raw))
        except (ValueError, ClientError, TimeoutError):
            self.approved = None
            _LOGGER.warning("Approved update catalog unavailable for %s", self.coordinator.device_id)

    async def _tick(self, _now):
        if self.pending and monotonic() - self.started > TIMEOUT:
            self.result = "timeout_unconfirmed"
            self.pending = None
            self.started = None
            self.deadline = None
            self._save_later()
        if monotonic() - self.last_catalog >= 300:
            await self._refresh_catalog()
        self.async_write_ha_state()

    async def async_install(self, version, backup, **kwargs):
        async with self.lock:
            if self.pending:
                raise HomeAssistantError("An update is already in progress")
            if not self.available or not self.coordinator.data.get("online"):
                raise HomeAssistantError("Agent or release catalog unavailable")
            # Refresh the approved catalog at time of install.
            await self._refresh_catalog()
            chosen = version or self.approved
            if not chosen or chosen != self.approved:
                raise HomeAssistantError("Only the approved catalog version can be installed")
            try:
                self.pending = make_request(self.installed, chosen, time())
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            self.started = monotonic()
            self.deadline = time() + TIMEOUT
            self.result = "requested"
            # Persist before sending; never replay a request on startup.
            if self.store is not None:
                try:
                    await self.store.async_save(self._snapshot())
                except Exception as err:
                    self.pending = None
                    self.started = self.deadline = None
                    self.result = "storage_failed"
                    raise HomeAssistantError("Could not persist update request") from err
            self.async_write_ha_state()
            try:
                await mqtt.async_publish(self.hass, self.root + "/command/update",
                                         json.dumps(self.pending), qos=0, retain=False)
            except Exception as err:
                self.pending = None
                self.started = None
                self.deadline = None
                self.result = "publish_failed"
                self._save_later()
                self.async_write_ha_state()
                raise HomeAssistantError("Could not publish update command") from err
