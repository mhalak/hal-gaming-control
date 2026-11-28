"""Device-scoped, fail-closed Unified MQTT telemetry v3 source.

The single Windows v3 stream is authoritative for live activity.
Verified HA accounting checkpoints remain intact; missing evidence never
becomes synthetic idle or gaming time.
"""
import json
import logging
from time import monotonic, time
from secrets import token_hex
from .diagnostic_protocol import decode_diagnostics

from homeassistant.components import mqtt
from homeassistant.core import callback

from .const import ROOT
from .error_registry import ErrorRegistry
from .app_registry import identity_key
from .protocol import parse_discovery
from .raw_foreground import HAOwnedForeground
from .screen_idle import DisplayGate
from .unified_telemetry import (
    MAX_AGE, TelemetryOrder, TelemetryTimestampError, decode_telemetry,
    display_v2, foreground_v2,
)


_LOGGER = logging.getLogger(__name__)


class ForegroundSource:
    """Consume only non-retained unified v3 for one gaming PC."""

    def __init__(self, hass, device_id, tracked_apps, on_update, *, intervals=(),
                 on_screen_off=None, errors=None):
        self.hass = hass
        self.device_id = device_id
        self.on_update = on_update
        self.errors = errors if errors is not None else ErrorRegistry()
        self._availability_seen = False
        self._online_since = None
        self._last_packet_at = None
        self._diagnostic_capable = False
        self._diagnostic_pending = None
        self._diagnostic_received = None
        self.ledger = HAOwnedForeground(device_id, tracked_apps, intervals=intervals)
        self.root = f"{ROOT}/{device_id}"
        self._connected = False
        self._online = False
        self._unsub = []
        self._closed = False
        self.last_raw = None  # latest verified foreground from unified v3
        # Latest read-only Windows foreground name, independent of the ledger.
        self.observed_game = None
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
        self._last_rejection_log = float('-inf')

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
            self._unsub.append(await mqtt.async_subscribe(
                self.hass, self.root + "/diagnostics/response",
                self._diagnostic_response, qos=0))
        except BaseException:
            self.close()
            raise

    @callback
    def _connection(self, connected):
        if self._closed:
            return
        was_connected = self._connected
        self._connected = connected is True
        if not self._connected:
            if was_connected:
                self.errors.report("HA_MQTT_DISCONNECTED")
            self._diagnostic_pending = self._diagnostic_received = None
            self._diagnostic_capable = False
            self.errors.remote_status = "Unavailable"
            self._availability_seen = False
            self._online_since = self._last_packet_at = None
            self._online = False
            self.last_raw = None
            self.observed_game = None
            self.ledger.invalidate()
            self.telemetry_order.suspend(retire=False)
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
        was_online = self._online
        self._availability_seen = True
        self._online = (message.topic == self.root + "/availability"
                        and value in ("online", b"online"))
        if self._online and not was_online:
            self._online_since = self._last_packet_at = None
        if not self._online:
            self._diagnostic_pending = self._diagnostic_received = None
            if self._diagnostic_capable:
                self.errors.remote_status = "Unavailable"
            self._online_since = self._last_packet_at = None
            self.errors.resolve("HA_TELEMETRY_MISSING")
            self.last_raw = None
            self.observed_game = None
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
        diagnostic_capable = False
        valid_discovery = False
        if message.topic == self.root + "/discovery":
            try:
                parse_discovery(message.topic, message.payload)
                raw = json.loads(message.payload)
                valid_discovery = True
                diagnostic_capable = (type(raw.get("diagnostics_protocol")) is int
                                      and raw["diagnostics_protocol"] == 1)
                capable = (
                    raw.get("device_id") == self.device_id
                    and type(raw.get("unified_telemetry_protocol")) is int
                    and raw["unified_telemetry_protocol"] == 3
                )
            except (ValueError, TypeError, RecursionError):
                pass
        diagnostic_changed = self._update_diagnostic_capability(diagnostic_capable, valid_discovery)
        if capable:
            self.errors.resolve("HA_PROTOCOL_UNSUPPORTED")
        elif self._online:
            self.errors.report("HA_PROTOCOL_UNSUPPORTED")
        if capable != self.v3_capable:
            self.v3_capable = capable
            if not capable:
                self.invalidate()
            else:
                self.on_update()
        elif diagnostic_changed or (not capable and self._online):
            self.on_update()

    def _update_diagnostic_capability(self, capable, valid):
        """Keep fresh reports on repeated discovery; distinguish legacy and invalid."""
        if capable and self._diagnostic_capable:
            return False
        status = "Waiting" if capable else "Not supported" if valid else "Unavailable"
        if capable == self._diagnostic_capable and self.errors.remote_status == status:
            return False
        self._diagnostic_capable = capable
        self._diagnostic_pending = self._diagnostic_received = None
        self.errors.remote_status = status
        return True

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

    def _display_game(self, packet):
        """Read-only validated foreground, independent of OFF accounting.

        Windows may still report Roblox in the foreground while the monitor
        is OFF and the gameplay ledger correctly observes idle. Only show
        the currently tracked HA game name; unknown/ambiguous is not a game.
        """
        foreground = packet["foreground"]
        if foreground["state"] == "idle":
            return "idle"
        if foreground["state"] != "foreground":
            return None
        try:
            key = identity_key(foreground["process"], foreground["signature"])
        except ValueError:
            return None
        app = self.ledger.apps.get(key)
        return app["name"] if app is not None else "idle"

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

    def _reset_epoch_evidence(self):
        """A new publisher epoch cannot inherit a pending ON sequence or usage."""
        self.ledger.invalidate()
        self.display.invalidate()
        self.last_raw = None
        self.observed_game = None
        self._needs_post_on = False
        self._post_on_sequence = self._post_on_timestamp = None
        # Retain the OFF latch and display ordering watermark; a fresh
        # accepted ON followed by fresh foreground must re-arm accounting.

    def _log_rejected_packet(self, error, mono):
        if mono - self._last_rejection_log >= 60:
            self._last_rejection_log = mono
            reason = ("Invalid unified telemetry timestamp"
                      if str(error) == "Invalid unified telemetry timestamp"
                      else "invalid unified telemetry envelope")
            _LOGGER.warning("Rejected v3 telemetry for %s: %s", self.device_id, reason)

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
        except (ValueError, TypeError, RecursionError) as error:
            code = (error.code if isinstance(error, TelemetryTimestampError)
                    else "HA_INVALID_TELEMETRY")
            delta = error.delta if isinstance(error, TelemetryTimestampError) else None
            self._last_packet_at = mono
            self.errors.resolve("HA_TELEMETRY_MISSING")
            self.errors.report(code, clock_delta_seconds=delta)
            self._log_rejected_packet(error, mono)
            self.invalidate()
            return
        previous_epoch = self.telemetry_order.epoch
        if not self.telemetry_order.accept(packet, monotonic_now=mono):
            return  # Duplicate/replay cannot mutate display or accounting.
        self._last_packet_at = mono
        self.errors.resolve("HA_TELEMETRY_MISSING")
        for code in ("HA_CLOCK_SKEW", "HA_TELEMETRY_STALE", "HA_INVALID_TELEMETRY"):
            self.errors.resolve(code)
        if previous_epoch is not None and previous_epoch != packet["epoch"]:
            self._reset_epoch_evidence()
        self.system_uptime = packet["system"]["uptime_seconds"]
        self.system_status = dict(packet["system"])
        display_state = self._v3_display(packet, wall, mono)
        # Parent-facing status must reflect the *accepted* display state,
        # not an OFF value that the event gate refused as untrusted.
        self.display_details = dict(packet["display"])
        self.display_details["reported_state"] = self.display_details["state"]
        self.display_details["state"] = display_state
        self.observed_game = self._display_game(packet)
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

    async def async_poll_diagnostics(self, _now=None):
        """Independent bounded challenge; no clock comparison with Windows."""
        if self._closed or not self._connected or not self._online or not self._diagnostic_capable:
            return
        now = monotonic()
        if self._diagnostic_received is None or now - self._diagnostic_received >= 15:
            self.errors.remote_status = "Unavailable"
            self.on_update()
        nonce = token_hex(16)
        self._diagnostic_pending = (nonce, now)
        try:
            await mqtt.async_publish(self.hass, self.root + "/diagnostics/request",
                                     nonce, qos=0, retain=False)
        except (ValueError, OSError, RuntimeError):
            self._diagnostic_pending = None

    @callback
    def _diagnostic_response(self, message):
        pending = self._diagnostic_pending
        now = monotonic()
        if (self._closed or not self._connected or not self._online
                or not self._diagnostic_capable or pending is None
                or message.topic != self.root + "/diagnostics/response"
                or not 0 <= now - pending[1] < 5):
            return
        try:
            packet = decode_diagnostics(message.payload, self.device_id, pending[0],
                                        retained=getattr(message, "retain", None))
        except (ValueError, TypeError, RecursionError):
            return
        self._diagnostic_pending = None
        self._diagnostic_received = now
        self.errors.update_remote(packet)
        self.on_update()

    def _diagnostic_health(self, observed):
        if not self._connected:
            self.errors.health = "Diagnostics unavailable"
            return
        self.errors.resolve("HA_MQTT_DISCONNECTED")
        if not self._online:
            self.errors.health = "Offline" if self._availability_seen else "Waiting for telemetry"
            return
        self.errors.health = "Online"
        if self._online_since is None or observed < self._online_since:
            self._online_since = observed
        last = self._last_packet_at
        if last is None or observed < last:
            last = self._online_since
        if observed - last >= MAX_AGE:
            self.errors.report("HA_TELEMETRY_MISSING")

    def current(self, monotonic_now=None):
        """Friendly HA alias, 'idle' or None (unknown/unavailable)."""
        observed = monotonic() if monotonic_now is None else monotonic_now
        self._diagnostic_health(observed)
        if not (self._connected and self._online) or self._closed:
            return None
        last = self.telemetry_order.received
        if (not self.v3_capable or last is None
                or not 0 <= observed - last < MAX_AGE):
            # Missing or stale evidence is unknown, not confirmed idle.
            self.last_raw = None
            self.observed_game = None
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
        self.observed_game = None
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
        self.observed_game = None
        self.ledger.invalidate()
        if self.display is not None:
            self.display.invalidate()
