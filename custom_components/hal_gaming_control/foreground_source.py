"""Device-scoped, fail-closed Unified MQTT telemetry v3 source.

The single Windows v3 stream is authoritative for live activity.
Verified HA accounting checkpoints remain intact; missing evidence never
becomes synthetic idle or gaming time.
"""
import json
from time import monotonic, time

from homeassistant.components import mqtt
from homeassistant.core import callback

from .const import ROOT
from .protocol import parse_discovery
from .raw_foreground import HAOwnedForeground
from .screen_idle import DisplayGate
from .unified_telemetry import (
    MAX_AGE, TelemetryOrder, decode_telemetry, display_v2, foreground_v2,
)


class ForegroundSource:
    """Consume only non-retained unified v3 for one gaming PC."""

    def __init__(self, hass, device_id, tracked_apps, on_update, *, intervals=(),
                 on_screen_off=None):
        self.hass = hass
        self.device_id = device_id
        self.on_update = on_update
        self.ledger = HAOwnedForeground(device_id, tracked_apps, intervals=intervals)
        self.root = f"{ROOT}/{device_id}"
        self._connected = False
        self._online = False
        self._unsub = []
        self._closed = False
        self.last_raw = None  # latest verified foreground from unified v3
        self.display = DisplayGate(device_id)
        # Only a verified OFF latches accounting off; unsupported UNKNOWN
        # observations must not deprive older PCs of normal v3 gaming time.
        self._screen_off_latched = False
        self.on_screen_off = on_screen_off
        self.telemetry_order = TelemetryOrder()
        self.v3_capable = False
        self.system_uptime = None
        self.system_status = None
        self.display_details = None
        self._needs_post_on = False
        self._post_on_sequence = None
        self._post_on_timestamp = None

    async def async_start(self):
        """Subscribe only to Unified v3; no legacy monitoring subscriptions."""
        self._connected = mqtt.is_connected(self.hass)
        try:
            self._unsub.append(mqtt.async_subscribe_connection_status(
                self.hass, self._connection))
            self._unsub.append(await mqtt.async_subscribe(
                self.hass, self.root + "/availability", self._availability, qos=1))
            self._unsub.append(await mqtt.async_subscribe(
                self.hass, self.root + "/discovery",
                self._v3_discovery, qos=1))
            self._unsub.append(await mqtt.async_subscribe(
                self.hass, self.root + "/state/telemetry",
                self._telemetry_snapshot, qos=0))
        except BaseException:
            self.close()
            raise

    @callback
    def _connection(self, connected):
        if self._closed:
            return
        self._connected = connected is True
        if not self._connected:
            self._online = False
            self.last_raw = None
            self.ledger.invalidate()
            self.telemetry_order.suspend()
            self.system_uptime = self.system_status = self.display_details = None
            self.v3_capable = False
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None
            if self.display is not None:
                self.display.invalidate()
        self.on_update()

    @callback
    def _availability(self, message):
        if self._closed:
            return
        value = message.payload
        self._online = (message.topic == self.root + "/availability"
                        and value in ("online", b"online"))
        if not self._online:
            self.last_raw = None
            self.ledger.invalidate()
            self.telemetry_order.suspend()
            self.system_uptime = self.system_status = self.display_details = None
            self.v3_capable = False
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None
            if self.display is not None:
                self.display.invalidate()
        self.on_update()

    @callback
    def _v3_discovery(self, message):
        if self._closed:
            return
        capable = False
        if message.topic == self.root + "/discovery":
            try:
                parse_discovery(message.topic, message.payload)
                raw = json.loads(message.payload)
                capable = (
                    raw.get("device_id") == self.device_id
                    and type(raw.get("unified_telemetry_protocol")) is int
                    and raw["unified_telemetry_protocol"] == 3
                )
            except (ValueError, TypeError, RecursionError):
                pass
        if capable != self.v3_capable:
            self.v3_capable = capable
            if not capable:
                self.invalidate()
            else:
                self.on_update()

    def _v3_display(self, packet, wall, mono):
        previous = self.display.current(mono)
        self._observe_display(display_v2(packet), wall, mono)
        current = self.display.current(mono)
        if current == "off":
            # Never infer return from missing or stale screen evidence.
            self._screen_off_latched = True
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None
        elif packet["display"]["state"] == "off":
            # The v3 envelope contains a fresh OFF observation, but its event
            # receipt failed DisplayGate ordering/consistency checks. Do not
            # conflate this with an unsupported UNKNOWN-only PC and silently
            # continue charging foreground gaming. Suspend without treating
            # the rejected event as verified OFF or awarding a bonus.
            self._screen_off_latched = True
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None
        elif current == "on" and previous != "on":
            # A new verified ON must be followed by a later foreground
            # observation, whether it is the first or a post-OFF ON.
            self._needs_post_on = True
            self._post_on_sequence = packet["sequence"]
            self._post_on_timestamp = (
                packet["observed_at"] - packet["display"]["event_age_ms"] / 1000)
        elif current == "unknown" and not self._screen_off_latched:
            # An unsupported helper with UNKNOWN must not block games.
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None
        return current

    def _post_on_ready(self, packet, display_state):
        if not self._screen_off_latched and not self._needs_post_on:
            # No previous verified OFF: unsupported UNKNOWN still counts
            # strictly validated foreground and never awards an idle bonus.
            return display_state != "off"
        if display_state != "on" or not self._needs_post_on:
            return False
        fg = packet["foreground"]
        age = fg["sample_age_ms"]
        return (age is not None and fg["state"] in ("foreground", "idle")
                and packet["sequence"] > self._post_on_sequence
                and packet["observed_at"] - age / 1000 > self._post_on_timestamp)

    def _v3_effective_foreground(self, packet, display_state, ready):
        raw = foreground_v2(packet)
        if ready:
            return raw
        adjusted = json.loads(raw)
        adjusted.update(
            state="idle" if display_state == "off" else "unknown",
            process=None, signature=None)
        return json.dumps(adjusted)

    def _v3_foreground(self, packet, wall, mono, display_state):
        ready = self._post_on_ready(packet, display_state)
        effective = self._v3_effective_foreground(packet, display_state, ready)
        accepted = self.ledger.observe(
            effective, retained=False, wall_now=wall, monotonic_now=mono)
        self.last_raw = None
        if (accepted and ready and
                packet["foreground"]["state"] == "foreground"):
            self.last_raw = json.loads(foreground_v2(packet))
        if accepted and ready and self._needs_post_on:
            self._screen_off_latched = False
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None

    @callback
    def _telemetry_snapshot(self, message):
        """Apply one ordered atomic v3 packet, display before foreground."""
        if self._closed or not self.v3_capable:
            return
        if (message.topic != self.root + "/state/telemetry"
                or not self._connected or not self._online):
            self.invalidate()
            return
        wall, mono = time(), monotonic()
        try:
            packet = decode_telemetry(
                message.payload, self.device_id,
                retained=getattr(message, "retain", None), wall_now=wall)
        except (ValueError, TypeError, RecursionError):
            self.invalidate()
            return
        if not self.telemetry_order.accept(packet, monotonic_now=mono):
            return  # Duplicate/replay cannot mutate display or accounting.
        self.system_uptime = packet["system"]["uptime_seconds"]
        self.system_status = dict(packet["system"])
        display_state = self._v3_display(packet, wall, mono)
        # Parent-facing status must reflect the *accepted* display state,
        # not an OFF value that the event gate refused as untrusted.
        self.display_details = dict(packet["display"])
        self.display_details["reported_state"] = self.display_details["state"]
        self.display_details["state"] = display_state
        self._v3_foreground(packet, wall, mono, display_state)
        self.on_update()

    def _observe_display(self, payload, wall, mono):
        """Preserve helper event identity and HA-owned bonus journal."""
        before = self.display.current(mono)
        active_before = self.ledger.current(mono)
        accepted, event = self.display.observe(
            payload, retained=False, wall_now=wall, monotonic_now=mono)
        after = self.display.current(mono)
        if before != after:
            self.ledger.invalidate()
            self.last_raw = None
        if (event is not None and active_before not in (None, "idle")
                and self.on_screen_off is not None):
            self.on_screen_off(event, self.ledger.export_segments())
        return accepted or before != after

    def current(self, monotonic_now=None):
        """Friendly HA alias, 'idle', or None (unknown/unavailable)."""
        if not (self._connected and self._online) or self._closed:
            return None
        observed = monotonic() if monotonic_now is None else monotonic_now
        last = self.telemetry_order.received
        if (not self.v3_capable or last is None
                or not 0 <= observed - last < MAX_AGE):
            # Missing or stale evidence is unknown, not confirmed idle.
            self.last_raw = None
            self.ledger.invalidate()
            self.system_uptime = self.system_status = self.display_details = None
            if self.display is not None:
                self.display.invalidate()
            return None
        if self.display is not None and self.display.current(observed) == "off":
            return "idle"
        return self.ledger.current(observed)

    def totals(self, now):
        """Confirmed-only daily/weekly totals; no liveness extrapolation."""
        return self.ledger.totals(now)

    def export_segments(self):
        return self.ledger.export_segments()

    def invalidate(self):
        self.last_raw = None
        self._needs_post_on = False
        self._post_on_sequence = self._post_on_timestamp = None
        self.ledger.invalidate()
        self.system_uptime = self.system_status = self.display_details = None
        if self.display is not None:
            self.display.invalidate()
        if not self._closed:
            self.on_update()

    def close(self):
        self._closed = True
        for unsubscribe in reversed(self._unsub):
            unsubscribe()
        self._unsub.clear()
        self._online = self._connected = False
        self.v3_capable = False
        self._needs_post_on = False
        self._post_on_sequence = self._post_on_timestamp = None
        self.last_raw = None
        self.ledger.invalidate()
        if self.display is not None:
            self.display.invalidate()
