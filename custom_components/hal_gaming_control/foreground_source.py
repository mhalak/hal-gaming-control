"""Device-scoped, fail-closed Home Assistant MQTT v2 foreground source.

The raw stream is authoritative for activity; Windows legacy game rules are
never consulted. The caller owns persistent accounting checkpoints and UI
registration, and must not backfill unavailable time.
"""
import json
from time import monotonic, time

from homeassistant.components import mqtt
from homeassistant.core import callback

from .const import ROOT
from .protocol import parse_discovery
from .raw_foreground import HAOwnedForeground, decode_raw_identity
from .screen_idle import DisplayGate
from .unified_telemetry import (
    MAX_AGE, TelemetryOrder, decode_telemetry, display_v2, foreground_v2,
)


class ForegroundSource:
    """Consume safe, non-retained v2 observations for one gaming PC."""

    def __init__(self, hass, device_id, tracked_apps, on_update, *, intervals=(),
                 screen_enabled=False, on_screen_off=None,
                 unified_enabled=False):
        self.hass = hass
        self.device_id = device_id
        self.on_update = on_update
        self.ledger = HAOwnedForeground(device_id, tracked_apps, intervals=intervals)
        self.root = f"{ROOT}/{device_id}"
        self._connected = False
        self._online = False
        self._unsub = []
        self._closed = False
        self.last_raw = None  # most recent independently verified live v2 packet
        self.display = DisplayGate(device_id) if screen_enabled else None
        self.on_screen_off = on_screen_off
        self.unified_enabled = unified_enabled
        self.telemetry_order = TelemetryOrder() if unified_enabled else None
        self.v3_capable = False
        self.system_uptime = None
        self.system_status = None
        self.display_details = None
        self._needs_post_on = False
        self._post_on_sequence = None
        self._post_on_timestamp = None

    async def async_start(self):
        """Subscribe to the same scoped MQTT topics in both discovery modes."""
        self._connected = mqtt.is_connected(self.hass)
        try:
            self._unsub.append(mqtt.async_subscribe_connection_status(
                self.hass, self._connection))
            self._unsub.append(await mqtt.async_subscribe(
                self.hass, self.root + "/availability", self._availability, qos=1))
            if self.unified_enabled:
                # Require the exact per-PC Windows v3 discovery capability;
                # a parent setting or old retained availability is not proof.
                self._unsub.append(await mqtt.async_subscribe(
                    self.hass, self.root + "/discovery",
                    self._v3_discovery, qos=1))
                # Strict either/or migration: never subscribe v2 and v3
                # accounting sources at the same time for one PC.
                self._unsub.append(await mqtt.async_subscribe(
                    self.hass, self.root + "/state/telemetry",
                    self._telemetry_snapshot, qos=0))
            else:
                self._unsub.append(await mqtt.async_subscribe(
                    self.hass, self.root + "/state/foreground_identity",
                    self._snapshot, qos=0))
                if self.display is not None:
                    self._unsub.append(await mqtt.async_subscribe(
                        self.hass, self.root + "/state/display_context",
                        self._screen_snapshot, qos=0))
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
            if self.telemetry_order is not None:
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
            if self.telemetry_order is not None:
                self.telemetry_order.suspend()
                self.system_uptime = self.system_status = self.display_details = None
                self.v3_capable = False
                self._needs_post_on = False
            if self.display is not None:
                self.display.invalidate()
        self.on_update()

    @callback
    def _snapshot(self, message):
        if self._closed:
            return
        if (message.topic != self.root + "/state/foreground_identity"
                or not self._connected or not self._online):
            self.last_raw = None
            self.ledger.invalidate()
            self.on_update()
            return
        payload = message.payload
        if self.display is not None and self.display.current(monotonic()) == "off":
            try:
                original = decode_raw_identity(payload, self.device_id)
                if original["state"] == "foreground":
                    # Preserve verified device/epoch/sequence/timestamp while
                    # gating counted foreground to confirmed console-idle.
                    original.update(state="idle", process=None, signature=None)
                    payload = json.dumps(original)
            except (ValueError, TypeError, RecursionError):
                pass  # Raw accounting still validates and fails closed.
        accepted = self.ledger.observe(
            payload, retained=getattr(message, "retain", None),
            wall_now=time(), monotonic_now=monotonic())
        self.last_raw = None
        if accepted:
            try:
                raw = decode_raw_identity(message.payload, self.device_id)
                if (raw["state"] == "foreground" and not (
                        self.display is not None and
                        self.display.current(monotonic()) == "off")):
                    self.last_raw = raw
            except (ValueError, TypeError, RecursionError):
                self.ledger.invalidate()
        self.on_update()

    @callback
    def _v3_discovery(self, message):
        if self._closed or not self.unified_enabled:
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
        if self.display is None:
            return None
        previous = self.display.current(mono)
        self._observe_display(display_v2(packet), wall, mono)
        current = self.display.current(mono)
        if previous != current and current == "on":
            self._needs_post_on = True
            self._post_on_sequence = packet["sequence"]
            # The helper event predates envelope capture by its age. A later
            # MQTT packet can still carry an older helper foreground sample.
            self._post_on_timestamp = (
                packet["observed_at"] - packet["display"]["event_age_ms"] / 1000)
        elif current != "on":
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None
        return current

    def _post_on_ready(self, packet, display_state):
        if self.display is None:
            return True
        if display_state != "on":
            return False
        if not self._needs_post_on:
            return True
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
            self._needs_post_on = False
            self._post_on_sequence = self._post_on_timestamp = None

    @callback
    def _telemetry_snapshot(self, message):
        """Apply one ordered atomic v3 packet, display before foreground."""
        if (self._closed or self.telemetry_order is None
                or not self.v3_capable):
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
        self.display_details = dict(packet["display"])
        display_state = self._v3_display(packet, wall, mono)
        self._v3_foreground(packet, wall, mono, display_state)
        self.on_update()

    def _observe_display(self, payload, wall, mono):
        """Shared v2 gate: keep exact helper event identity and bonus journal."""
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

    @callback
    def _screen_snapshot(self, message):
        """Display and foreground are independent, device-scoped live streams."""
        if self._closed or self.display is None:
            return
        if (message.topic != self.root + "/state/display_context"
                or not self._connected or not self._online):
            self.display.invalidate()
            self.ledger.invalidate()
            self.last_raw = None
            self.on_update()
            return
        if getattr(message, "retain", None) is not False:
            self.display.invalidate()
            self.ledger.invalidate()
            self.last_raw = None
            self.on_update()
            return
        if self._observe_display(message.payload, time(), monotonic()):
            self.on_update()

    def current(self, monotonic_now=None):
        """Friendly HA alias, 'idle', or None (unknown/unavailable)."""
        if not (self._connected and self._online) or self._closed:
            return None
        observed = monotonic() if monotonic_now is None else monotonic_now
        if self.telemetry_order is not None:
            last = self.telemetry_order.received
            if (not self.v3_capable or last is None
                    or not 0 <= observed - last < MAX_AGE):
                # A cached OFF cannot appear to be freshly confirmed idle
                # after v3 telemetry stops; do not extrapolate across gaps.
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
        self.last_raw = None
        self.ledger.invalidate()
        if self.display is not None:
            self.display.invalidate()
