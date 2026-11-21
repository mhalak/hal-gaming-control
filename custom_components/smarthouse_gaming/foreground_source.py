"""Device-scoped HA MQTT source for the raw foreground identity (issue #65).

One instance owns exactly three subscriptions for one Windows agent: its
availability topic, its ``state/foreground_identity`` topic and the broker
connection status. It is receive-only: nothing is published and no Windows
configuration is sent. Application names are resolved here from the HA-side
tracked applications, never from any legacy Windows process/game data.

``current()`` returns a tracked application's friendly name, ``"idle"`` for a
confirmed foreground that is not tracked, or ``None`` for everything that is
unconfirmed (offline, unknown, stale, ambiguous Java, broker interruption,
rejected input). ``None`` must be rendered as unavailable, never as idle.
"""
import json
import logging
import time

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .const import ROOT
from .foreground_snapshot import MAX_SAMPLE_AGE
from .raw_foreground import HAOwnedForeground

_LOGGER = logging.getLogger(__name__)
_EXPIRY_MARGIN = 0.05


def _wall():
    return time.time()


def _mono():
    return time.monotonic()


class ForegroundSource:
    """Subscribe to one device's raw foreground and expose a fail-closed value."""

    def __init__(self, hass, device_id, tracked_apps, on_update, *, intervals=()):
        self.hass = hass
        self.device_id = device_id
        self._on_update = on_update
        self._foreground = HAOwnedForeground(device_id, tracked_apps, intervals=intervals)
        root = f"{ROOT}/{device_id}"
        self._availability_topic = root + "/availability"
        self._identity_topic = root + "/state/foreground_identity"
        self._unsubscribers = []
        self._timer = None
        self._connected = False
        self._online = False
        self._closed = False

    async def async_start(self):
        """Subscribe to this device's topics only; release everything on failure."""
        if self._unsubscribers or self._closed:
            return
        self._connected = mqtt.is_connected(self.hass)
        try:
            self._unsubscribers.append(await mqtt.async_subscribe(
                self.hass, self._availability_topic, self._availability, qos=1, encoding=None))
            self._unsubscribers.append(
                mqtt.async_subscribe_connection_status(self.hass, self._connection))
            self._unsubscribers.append(await mqtt.async_subscribe(
                self.hass, self._identity_topic, self._message, qos=0, encoding=None))
        except BaseException:
            self.close()
            raise

    @callback
    def close(self):
        """Release every subscription and timer; later messages are ignored."""
        self._closed = True
        self._cancel_timer()
        unsubscribers, self._unsubscribers = self._unsubscribers, []
        for unsubscribe in unsubscribers:
            unsubscribe()
        self._foreground.invalidate()

    def current(self, monotonic_now):
        if self._closed or not (self._connected and self._online):
            return None
        return self._foreground.current(monotonic_now)

    def totals(self, now):
        return self._foreground.totals(now)

    def export_segments(self):
        return self._foreground.export_segments()

    def invalidate(self):
        """Discard unconfirmed evidence; the value becomes None until fresh data."""
        self._cancel_timer()
        self._foreground.invalidate()

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer()
            self._timer = None

    def _notify(self):
        try:
            self._on_update()
        except Exception:  # noqa: BLE001 - a listener bug must not break MQTT handling
            _LOGGER.exception("Foreground update listener failed")

    def _drop(self):
        self.invalidate()
        self._notify()

    @callback
    def _connection(self, connected):
        if self._closed:
            return
        self._connected = bool(connected)
        if not connected:
            self._drop()

    @callback
    def _availability(self, message):
        if self._closed:
            return
        self._online = message.payload == b"online"
        if not self._online:
            self._drop()

    @callback
    def _message(self, message):
        if self._closed:
            return
        wall, mono = _wall(), _mono()
        payload = message.payload
        accepted = (message.topic == self._identity_topic and not message.retain
                    and self._connected and self._online
                    and self._foreground.observe(
                        payload, retained=False, wall_now=wall, monotonic_now=mono))
        if not accepted:
            self._drop()
            return
        self._arm_expiry(payload, wall)
        self._notify()

    def _arm_expiry(self, payload, wall):
        """Signal staleness even when no further message arrives."""
        self._cancel_timer()
        age = max(0.0, wall - json.loads(payload)["observed_at"])
        delay = max(0.0, MAX_SAMPLE_AGE - age) + _EXPIRY_MARGIN
        self._timer = async_call_later(self.hass, delay, self._expired)

    @callback
    def _expired(self, _now):
        self._timer = None
        if not self._closed:
            self._foreground.invalidate()
            self._notify()
