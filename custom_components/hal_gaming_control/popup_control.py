"""HA-owned generic popup channel; no Windows-side policy or implicit fallback.

Protocol v1 stays available for legacy one-shot forms. Protocol v2 adds
independent fields and update-only live synchronization.
"""
import asyncio
from datetime import timedelta
import json
import re
import secrets
from time import time

from homeassistant.components import mqtt
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval

from .const import ROOT
from .protocol import parse_discovery
from .popup_view import MODES, automatic_patch


def _no_duplicate_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate popup response field")
        value[key] = item
    return value


def _decode_response(payload):
    if not isinstance(payload, (str, bytes)) or not 0 < len(payload) <= 1024:
        return None
    try:
        return json.loads(payload, object_pairs_hook=_no_duplicate_fields)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None


def _valid_response(packet, *, device_id, popup_id, buttons):
    if (type(packet) is not dict
            or type(packet.get("version")) is not int or packet["version"] != 1
            or packet.get("device_id") != device_id
            or packet.get("popup_id") != popup_id
            or type(packet.get("event_id")) is not str
            or re.fullmatch(r"[0-9a-f]{32}", packet["event_id"]) is None):
        return False
    base = {"version", "device_id", "popup_id", "event_id", "kind"}
    if packet.get("kind") == "closed":
        return packet.keys() == base
    if packet.get("kind") == "button":
        return (packet.keys() == base | {"button_id"}
                and type(packet["button_id"]) is str
                and packet["button_id"] in buttons)
    return False


class PopupControl:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.root = f"{ROOT}/{coordinator.device_id}"
        self._supported = False
        self._v2 = False
        self._lock = asyncio.Lock()
        self._live_options = None
        self._sync_unsubscribe = None
        self._popup_version = 1
        self._unsubscribe = None
        self._event_unsubscribe = None
        self._buttons = set()
        self._seen_events = []
        self._epoch = secrets.token_hex(16)
        self._sequence = 0
        self._popup_id = None

    @property
    def supports_v2(self):
        return self._supported and self._v2

    def _stop_sync(self):
        self._live_options = None
        if self._sync_unsubscribe is not None:
            self._sync_unsubscribe()
            self._sync_unsubscribe = None

    def _start_sync(self, options):
        self._live_options = dict(options)
        self._sync_unsubscribe = async_track_time_interval(
            self.coordinator.hass, self._tick, timedelta(seconds=5))

    async def _tick(self, _now):
        await self.async_sync()

    async def async_start(self):
        self._unsubscribe = await mqtt.async_subscribe(
            self.coordinator.hass, self.root + "/discovery",
            self._on_discovery, qos=1)
        self._event_unsubscribe = await mqtt.async_subscribe(
            self.coordinator.hass, self.root + '/ui/popup_event',
            self._on_popup_event, qos=1)

    @callback
    def _on_discovery(self, message):
        self._supported = False
        self._v2 = False
        try:
            parsed = parse_discovery(message.topic, message.payload)
            raw = json.loads(message.payload)
            self._supported = (
                parsed["device_id"] == self.coordinator.device_id
                and type(raw.get("unified_telemetry_protocol")) is int
                and raw["unified_telemetry_protocol"] == 3
                and type(raw.get("popup_ui_protocol")) is int
                and raw["popup_ui_protocol"] == 1)
            versions = raw.get("popup_ui_protocols")
            self._v2 = (self._supported and type(versions) is list and versions == [1, 2]
                        and all(type(version) is int for version in versions))
        except (ValueError, TypeError, KeyError, RecursionError):
            pass
        if not self.supports_v2:
            self._stop_sync()

    @callback
    def _on_popup_event(self, message):
        """Child clicks/closing are observations, never permission grants."""
        if (getattr(message, "retain", None) is not False
                or message.topic != self.root + "/ui/popup_event"
                or self._popup_id is None or not self._supported):
            return
        packet = _decode_response(message.payload)
        if not _valid_response(
                packet, device_id=self.coordinator.device_id,
                popup_id=self._popup_id, buttons=self._buttons):
            return
        if packet["event_id"] in self._seen_events:
            return
        self._seen_events.append(packet["event_id"])
        self._seen_events = self._seen_events[-64:]
        self.coordinator.hass.bus.async_fire(
            "hal_gaming_control_popup_response", {
                "device_id": self.coordinator.device_id,
                "entry_id": self.coordinator.entry.entry_id,
                "popup_id": self._popup_id,
                "event_id": packet["event_id"], "kind": packet["kind"],
                **({"button_id": packet["button_id"]}
                   if packet["kind"] == "button" else {}),
            })
        if packet["kind"] == "closed" and self._popup_version == 2:
            self._stop_sync()
            self._popup_id = None
            self._buttons = set()

    def _ensure_ready(self):
        c = self.coordinator
        if not self._supported:
            raise HomeAssistantError(
                "Windows agent does not advertise popup UI protocol v1; "
                "install a compatible agent before calling this action")
        if (c.foreground is None or not c.storage_healthy
                or not mqtt.is_connected(c.hass)
                or c.foreground.current() is None):
            raise HomeAssistantError("Gaming PC is offline or telemetry is stale")

    async def _publish(self, operation, version, popup_id, view=None, *, live=False):
        self._sequence += 1
        stale = 120
        if live:
            stale = 30
        elif operation == "upsert":
            stale = min(3600, max(120, (view["remaining_seconds"] or
                                      view.get("progress_seconds") or 0) + 180))
        packet = {
            "version": version, "device_id": self.coordinator.device_id,
            "producer_epoch": self._epoch, "sequence": self._sequence,
            "issued_at": int(time()), "message_ttl_seconds": 15,
            "display_stale_after_seconds": stale, "popup_id": popup_id,
            "operation": operation,
        }
        if view is not None:
            packet["view"] = view
        await mqtt.async_publish(
            self.coordinator.hass, self.root + "/ui/popup",
            json.dumps(packet, separators=(",", ":")), qos=1, retain=False)

    async def async_send(self, operation, *, heading=None, description=None,
                         remaining_seconds=None, progress_percent=None,
                         buttons=None, countdown_running=None, progress_seconds=None,
                         live_options=None):
        async with self._lock:
            self._ensure_ready()
            if operation == "hide":
                await self._hide()
                return
            version = 2 if countdown_running is not None else 1
            if version == 2 and not self.supports_v2:
                raise HomeAssistantError("Windows popup protocol v2 is unavailable")
            self._stop_sync()
            popup_id = (secrets.token_hex(16) if version == 2
                        else self._popup_id or secrets.token_hex(16))
            view = {"heading": heading, "description": description,
                    "remaining_seconds": remaining_seconds,
                    "progress_percent": progress_percent, "buttons": buttons or []}
            live = version == 2 and live_options is not None and any(
                live_options[mode] == "automatic" for mode in MODES)
            if version == 2:
                view.update(countdown_running=countdown_running, progress_seconds=progress_seconds)
            self._popup_id, self._popup_version = popup_id, version
            self._buttons = {row["id"] for row in view["buttons"]}
            self._seen_events = []
            try:
                await self._publish("upsert", version, popup_id, view, live=live)
            except BaseException:
                self._popup_id = None
                self._buttons = set()
                raise
            # A close arriving while MQTT publishes must not rearm the session.
            if live and self._popup_id == popup_id and self.supports_v2:
                self._start_sync(live_options)

    async def _hide(self):
        version = self._popup_version
        if version == 2 and not self.supports_v2:
            version = 1
        popup_id = self._popup_id or secrets.token_hex(16)
        self._stop_sync()
        self._popup_id = None
        self._buttons = set()
        self._seen_events = []
        await self._publish("hide", version, popup_id)

    async def async_sync(self):
        """Refresh only an explicitly shown automatic v2 form."""
        async with self._lock:
            if self._live_options is None or self._popup_id is None:
                return
            try:
                self._ensure_ready()
                if not self.supports_v2:
                    raise HomeAssistantError("Windows popup protocol v2 is unavailable")
                view = automatic_patch(self.coordinator, self._live_options, v2=True)
            except HomeAssistantError:
                # A connected agent can hide immediately; otherwise its short
                # display lease expires. Recovery never shows a new popup.
                try:
                    self._ensure_ready()
                    await self._hide()
                except HomeAssistantError:
                    self._stop_sync()
                    self._popup_id = None
                    self._buttons = set()
                return
            try:
                await self._publish("refresh", 2, self._popup_id, view, live=True)
            except HomeAssistantError:
                self._stop_sync()
                self._popup_id = None
                self._buttons = set()

    def close(self):
        self._stop_sync()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._event_unsubscribe is not None:
            self._event_unsubscribe()
            self._event_unsubscribe = None
        self._supported = False
        self._v2 = False
        self._popup_id = None
        self._buttons = set()
        self._seen_events = []
