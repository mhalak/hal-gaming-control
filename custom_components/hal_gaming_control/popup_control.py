"""HA-owned generic popup channel; no Windows-side policy or implicit fallback.

The Windows agent must explicitly advertise popup_ui_protocol=1 before this
publisher can be used. An older agent never silently accepts a no-op action.
"""
import json
import re
import secrets
from time import time

from homeassistant.components import mqtt
from homeassistant.exceptions import HomeAssistantError

from .const import ROOT
from .protocol import parse_discovery


class PopupControl:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.root = f"{ROOT}/{coordinator.device_id}"
        self._supported = False
        self._unsubscribe = None
        self._event_unsubscribe = None
        self._buttons = set()
        self._seen_events = []
        self._epoch = secrets.token_hex(16)
        self._sequence = 0
        self._popup_id = None

    async def async_start(self):
        self._unsubscribe = await mqtt.async_subscribe(
            self.coordinator.hass, self.root + "/discovery",
            self._on_discovery, qos=1)
        self._event_unsubscribe = await mqtt.async_subscribe(
            self.coordinator.hass, self.root + '/ui/popup_event',
            self._on_popup_event, qos=1)

    def _on_discovery(self, message):
        self._supported = False
        try:
            parsed = parse_discovery(message.topic, message.payload)
            raw = json.loads(message.payload)
            self._supported = (
                parsed["device_id"] == self.coordinator.device_id
                and type(raw.get("unified_telemetry_protocol")) is int
                and raw["unified_telemetry_protocol"] == 3
                and type(raw.get("popup_ui_protocol")) is int
                and raw["popup_ui_protocol"] == 1)
        except (ValueError, TypeError, KeyError, RecursionError):
            pass

    def _on_popup_event(self, message):
        """Expose child clicks/closing as HA events, never grant time here."""
        if (getattr(message, "retain", None) is not False
                or message.topic != self.root + "/ui/popup_event"
                or self._popup_id is None or not self._supported):
            return
        if (not isinstance(message.payload, (str, bytes))
                or not 0 < len(message.payload) <= 1024):
            return
        try:
            def unique(pairs):
                obj = {}
                for key, value in pairs:
                    if key in obj:
                        raise ValueError("Duplicate popup response field")
                    obj[key] = value
                return obj
            packet = json.loads(message.payload, object_pairs_hook=unique)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return
        if (type(packet) is not dict
                or type(packet.get("version")) is not int
                or packet["version"] != 1
                or packet.get("device_id") != self.coordinator.device_id
                or packet.get("popup_id") != self._popup_id
                or type(packet.get("event_id")) is not str
                or re.fullmatch(r"[0-9a-f]{32}", packet["event_id"]) is None):
            return
        kind = packet.get("kind")
        if kind == "closed":
            if packet.keys() != {"version", "device_id", "popup_id",
                                 "event_id", "kind"}:
                return
        elif kind == "button":
            if (packet.keys() != {"version", "device_id", "popup_id",
                                  "event_id", "kind", "button_id"}
                    or type(packet["button_id"]) is not str
                    or packet["button_id"] not in self._buttons):
                return
        else:
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
                "event_id": packet["event_id"], "kind": kind,
                **({"button_id": packet["button_id"]}
                   if kind == "button" else {}),
            })

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

    async def async_send(self, operation, *, heading=None, description=None,
                         remaining_seconds=None, progress_percent=None,
                         buttons=None):
        self._ensure_ready()
        self._sequence += 1
        popup_id = self._popup_id or secrets.token_hex(16)
        packet = {
            "version": 1,
            "device_id": self.coordinator.device_id,
            "producer_epoch": self._epoch,
            "sequence": self._sequence,
            "issued_at": int(time()),
            "message_ttl_seconds": 15,
            "display_stale_after_seconds": 120,
            "popup_id": popup_id,
            "operation": operation,
        }
        if operation == "upsert":
            packet["view"] = {
                "heading": heading, "description": description,
                "remaining_seconds": remaining_seconds,
                "progress_percent": progress_percent,
                "buttons": buttons if buttons is not None else [],
            }
        # QoS 1 non-retained; agent must validate TTL, epoch and sequence.
        await mqtt.async_publish(
            self.coordinator.hass, self.root + "/ui/popup",
            json.dumps(packet, separators=(",", ":")),
            qos=1, retain=False)
        self._popup_id = popup_id if operation == "upsert" else None
        self._buttons = ({row["id"] for row in (buttons or [])}
                         if operation == "upsert" else set())
        self._seen_events = [] if operation == "hide" else self._seen_events

    def close(self):
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._event_unsubscribe is not None:
            self._event_unsubscribe()
            self._event_unsubscribe = None
        self._supported = False
        self._popup_id = None
        self._buttons = set()
        self._seen_events = []
