"""Device-scoped, fail-closed Home Assistant MQTT v2 foreground source.

The raw stream is authoritative for activity; Windows legacy game rules are
never consulted. The caller owns persistent accounting checkpoints and UI
registration, and must not backfill unavailable time.
"""
from time import monotonic, time

from homeassistant.components import mqtt
from homeassistant.core import callback

from .const import ROOT
from .raw_foreground import HAOwnedForeground, decode_raw_identity


class ForegroundSource:
    """Consume safe, non-retained v2 observations for one gaming PC."""

    def __init__(self, hass, device_id, tracked_apps, on_update, *, intervals=()):
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
        accepted = self.ledger.observe(
            message.payload, retained=getattr(message, "retain", None),
            wall_now=time(), monotonic_now=monotonic())
        self.last_raw = None
        if accepted:
            try:
                raw = decode_raw_identity(message.payload, self.device_id)
                if raw["state"] == "foreground":
                    self.last_raw = raw
            except (ValueError, TypeError, RecursionError):
                self.ledger.invalidate()
        self.on_update()

    def current(self, monotonic_now=None):
        """Friendly HA alias, 'idle', or None (unknown/unavailable)."""
        if not (self._connected and self._online) or self._closed:
            return None
        return self.ledger.current(
            monotonic() if monotonic_now is None else monotonic_now)

    def totals(self, now):
        """Confirmed-only daily/weekly totals; no liveness extrapolation."""
        return self.ledger.totals(now)

    def export_segments(self):
        return self.ledger.export_segments()

    def invalidate(self):
        self.last_raw = None
        self.ledger.invalidate()
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
