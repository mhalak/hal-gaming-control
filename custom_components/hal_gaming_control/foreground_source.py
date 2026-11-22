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
from .raw_foreground import HAOwnedForeground, decode_raw_identity
from .screen_idle import DisplayGate
from .unified_telemetry import (
    TelemetryOrder, decode_telemetry, display_v2, foreground_v2,
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
        self.system_uptime = None
        self.system_status = None
        self.display_details = None
        self._needs_post_on = False

    async def async_start(self):
        """Subscribe to the same scoped MQTT topics in both discovery modes."""
        self._connected = mqtt.is_connected(self.hass)
        try:
            self._unsub.append(mqtt.async_subscribe_connection_status(
                self.hass, self._connection))
            self._unsub.append(await mqtt.async_subscribe(
                self.hass, self.root + "/availability", self._availability, qos=1))
            if self.unified_enabled:
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
                self._needs_post_on = False
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
    def _telemetry_snapshot(self, message):
        """Apply one ordered, atomic v3 observation; display BEFORE foreground."""
        if self._closed or self.telemetry_order is None:
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
            return  # Replay is not new evidence, nor does it reset old evidence.
        self.system_uptime = packet["system"]["uptime_seconds"]
        self.system_status = dict(packet["system"])
        self.display_details = dict(packet["display"])
        if self.display is not None:
            previous = self.display.current(mono)
            self._observe_display(display_v2(packet), wall, mono)
            current = self.display.current(mono)
            if previous != current and current == "on":
                self._needs_post_on = True
            elif current != "on":
                self._needs_post_on = False

        # The raw process may still be focused while the display is off.
        # OFF -> idle; unknown/first ON -> unknown; never invent another
        # measured foreground interval from a Windows power-plan timeout.
        raw = packet["foreground"]
        transformed = foreground_v2(packet)
        display_state = self.display.current(mono) if self.display is not None else None
        if self.display is not None and (
                display_state == "off" or display_state != "on"
                or self._needs_post_on):
            adjusted = json.loads(transformed)
            if display_state == "off":
                adjusted.update(state="idle", process=None, signature=None)
            else:
                adjusted.update(state="unknown", process=None, signature=None)
            transformed = json.dumps(adjusted)
        accepted = self.ledger.observe(
            transformed, retained=False, wall_now=wall, monotonic_now=mono)
        self.last_raw = None
        if (accepted and raw["state"] == "foreground"
                and (self.display is None or
                     (display_state == "on" and not self._needs_post_on))):
            self.last_raw = json.loads(foreground_v2(packet))
        if self._needs_post_on and display_state == "on":
            self._needs_post_on = False  # Next v3 packet must prove focus again.
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
        self.last_raw = None
        self.ledger.invalidate()
        if self.display is not None:
            self.display.invalidate()
