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


class ForegroundSource:
    """Consume safe, non-retained v2 observations for one gaming PC."""

    def __init__(self, hass, device_id, tracked_apps, on_update, *, intervals=(),
                 screen_enabled=False, on_screen_off=None):
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

    async def async_start(self):
        """Subscribe to the same scoped MQTT topics in both discovery modes."""
        self._connected = mqtt.is_connected(self.hass)
        try:
            self._unsub.append(mqtt.async_subscribe_connection_status(
                self.hass, self._connection))
            self._unsub.append(await mqtt.async_subscribe(
                self.hass, self.root + "/availability", self._availability, qos=1))
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
        wall, mono = time(), monotonic()
        before = self.display.current(mono)
        active_before = self.ledger.current(mono)
        accepted, event = self.display.observe(
            message.payload, retained=getattr(message, "retain", None),
            wall_now=wall, monotonic_now=mono)
        after = self.display.current(mono)
        if not accepted and before == after:
            return  # Duplicate/out-of-order packet; no new state evidence.
        if before != after:
            self.ledger.invalidate()  # Prevent charging across OFF/ON changes.
            self.last_raw = None
        if (event is not None and active_before not in (None, "idle")
                and self.on_screen_off is not None):
            self.on_screen_off(event, self.ledger.export_segments())
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
