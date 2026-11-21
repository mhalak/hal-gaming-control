"""Native Config / Options Flow with manual-action ownership."""
import asyncio
import logging
import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
from .const import DOMAIN, ROOT
from .candidate_protocol import parse_candidate
from .app_registry import load_apps, normalized_name
from .app_editor import (apply_app_editor, editor_choices, editor_rows,
                         raw_label)
from .direct_mqtt import direct_mode
from .protocol import parse_discovery
from .raw_foreground import decode_raw_identity

_LOGGER = logging.getLogger(__name__)

# The user step listens only for this bounded window; retained discovery payloads arrive immediately.
DISCOVERY_WINDOW = 3.0
DISCOVERY_FILTER = "SmartHouse/Gaming/+/discovery"
MAX_DISCOVERY_PAYLOAD = 65536
RAW_SNAPSHOT_MAX_AGE = 8.0
RAW_SNAPSHOT_FUTURE_SKEW = 2.0


async def _listen_window():
    await asyncio.sleep(DISCOVERY_WINDOW)


def _collect(found, message):
    """Validate one discovery message; ignore anything invalid, oversized or foreign. Never raises."""
    try:
        payload = message.payload
        if not isinstance(payload, (str, bytes)) or len(payload) > MAX_DISCOVERY_PAYLOAD:
            return
        device = parse_discovery(message.topic, payload)
        found[device["device_id"]] = device
    except Exception:  # noqa: BLE001 - foreign/garbled payloads must not break the flow
        return


async def _discover_devices(hass):
    """Subscribe through the mqtt integration (works with HA MQTT discovery disabled)."""
    found = {}
    unsubscribe = None
    try:
        unsubscribe = await mqtt.async_subscribe(hass, DISCOVERY_FILTER, lambda m: _collect(found, m), qos=1)
        await _listen_window()
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001
        if unsubscribe is None:
            _LOGGER.warning("Cannot subscribe to gaming discovery (%s)", type(err).__name__)
            return found
        raise
    finally:
        if unsubscribe is not None:
            unsubscribe()
    return found



async def _discover_foreground_candidate(hass, device_id):
    """Briefly listen for a fresh, non-retained candidate from this PC only."""
    topic = f"{ROOT}/{device_id}/state/foreground_candidate"
    found = {}
    unsubscribe = None

    def collect(message):
        try:
            candidate = parse_candidate(
                message.topic, message.payload, device_id,
                retained=message.retain, now=dt_util.utcnow().timestamp())
        except (ValueError, TypeError):
            return
        found["candidate"] = candidate

    try:
        unsubscribe = await mqtt.async_subscribe(hass, topic, collect, qos=0)
        await _listen_window()
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001 - no candidate is a safe outcome
        _LOGGER.debug("Foreground candidate unavailable (%s)", type(err).__name__)
    finally:
        if unsubscribe is not None:
            unsubscribe()
    return found.get("candidate")


async def _discover_raw_foreground_snapshot(hass, device_id):
    """Read only a current, device-scoped v2 raw identity; never cache old samples."""
    topic = f"{ROOT}/{device_id}/state/foreground_identity"
    found = {}
    unsubscribe = None

    def collect(message):
        if message.topic != topic or getattr(message, "retain", None) is not False:
            return
        try:
            packet = decode_raw_identity(message.payload, device_id)
            age = dt_util.utcnow().timestamp() - packet["observed_at"]
        except (ValueError, TypeError, KeyError):
            return
        if -RAW_SNAPSHOT_FUTURE_SKEW <= age < RAW_SNAPSHOT_MAX_AGE:
            found["packet"] = packet

    try:
        unsubscribe = await mqtt.async_subscribe(hass, topic, collect, qos=0)
        await _listen_window()
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001 - absent data is unavailable, never idle
        _LOGGER.debug("Raw foreground snapshot unavailable (%s)", type(err).__name__)
    finally:
        if unsubscribe is not None:
            unsubscribe()
    return found.get("packet")


def _raw_foreground_labels(snapshot, apps):
    """Separate actual executable identity from the HA-normalized display."""
    if snapshot is None:
        return "unavailable", "unavailable"
    state = snapshot["state"]
    if state == "idle":
        return "idle", "idle"
    if state == "unknown":
        return "unknown", "unavailable"
    raw = raw_label(snapshot)  # Validated basename + optional safe Java signature
    mapped = normalized_name(apps, snapshot["process"], snapshot["signature"])
    if mapped is not None:
        return raw, mapped
    # Unknown executable is idle for tracked gameplay, but bare Java is
    # ambiguous and must not silently be described as a specific game.
    if snapshot["process"].casefold() in ("java.exe", "javaw.exe") and not snapshot["signature"]:
        return raw, "unavailable"
    return raw, "idle"


def _candidate_matches_raw(candidate, snapshot):
    """Do not suggest enrolling a different process from the one just shown."""
    return (snapshot is None or (
        snapshot["state"] == "foreground" and
        isinstance(candidate, dict) and
        candidate.get("process", "").casefold() ==
        snapshot["process"].casefold() and
        candidate.get("signature") == snapshot["signature"]))


class GamingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_mqtt(self, discovery_info):
        try:
            self.device = parse_discovery(discovery_info.topic, discovery_info.payload)
        except (ValueError, TypeError) as err:
            _LOGGER.debug("Rejected gaming MQTT discovery (%s)", type(err).__name__)
            return self.async_abort(reason="invalid_discovery")
        _LOGGER.debug("Received valid gaming MQTT discovery for device %s", self.device["device_id"])
        await self.async_set_unique_id(self.device["device_id"])
        self._abort_if_unique_id_configured(updates=self.device)
        self.context["title_placeholders"] = {"name": self.device["name"]}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=self.device["name"], data=self.device)
        return self.async_show_form(step_id="confirm",
            description_placeholders={"name": self.device["name"]})

    async def async_step_user(self, user_input=None):
        if user_input is None:
            configured = self._async_current_ids()
            found = await _discover_devices(self.hass)
            self._devices = {k: v for k, v in sorted(found.items()) if k not in configured}
            if not self._devices:
                return self.async_abort(reason="no_devices_found")
        elif user_input["device"] not in getattr(self, "_devices", {}):
            return self.async_abort(reason="no_devices_found")
        else:
            self.device = self._devices[user_input["device"]]
            await self.async_set_unique_id(self.device["device_id"], raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_confirm({})
        options = [{"value": k, "label": v["name"]} for k, v in self._devices.items()]
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("device"): selector.SelectSelector(selector.SelectSelectorConfig(options=options))}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GamingOptionsFlow()


def _mqtt_broker_details(hass):
    """Read non-secret facts from HA's single shared MQTT config entry."""
    entries = hass.config_entries.async_entries("mqtt")
    if not entries:
        return "Not configured", "Unknown", "Unknown"
    if len(entries) != 1:
        return "Not available", "Unknown", "Unknown"
    data = entries[0].data
    raw = data.get("broker")
    broker = (raw if isinstance(raw, str)
              and re.fullmatch(r"[A-Za-z0-9_.:\-\[\]]{1,255}", raw)
              else "Not available")
    port = data.get("port")
    port_label = str(port) if type(port) is int and 1 <= port <= 65535 else "Unknown"
    tls_label = "Yes" if data.get("certificate") else "No"
    return broker, port_label, tls_label


def _new_candidate_label(candidate, baseline):
    """Show a confirmed untracked app, never generic or unsafe Java."""
    if not isinstance(candidate, dict):
        return None
    from .app_registry import identity_key
    try:
        key = identity_key(candidate["process"], candidate.get("signature"))
        return raw_label(candidate) if key not in load_apps(baseline) else None
    except (KeyError, ValueError, TypeError):
        return None


class GamingOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return await self.async_step_settings_menu()

    async def async_step_settings_menu(self, user_input=None):
        # Use a new translation key so old, cached "actions" descriptions
        # cannot be used for the two-option Configure menu.
        # Explicit labels also work with older frontend translation caches.
        return self.async_show_menu(
            step_id="settings_menu",
            menu_options={
                "mqtt_settings": "MQTT configuration",
                "tracked_apps": "Tracked applications",
            },
        )

    async def async_step_mqtt_settings(self, user_input=None):
        """Show the shared connection and per-device topics without exposing secrets."""
        if user_input is not None:
            return await self.async_step_settings_menu()
        root = f"{ROOT}/{self.config_entry.data['device_id']}"
        broker, port, tls = _mqtt_broker_details(self.hass)
        connected = mqtt.is_connected(self.hass)
        help_text = ("No action needed: Home Assistant is connected to its MQTT broker."
                     if connected else
                     "Open Settings → Devices & services → MQTT to check the connection, then review the Home Assistant log.")
        return self.async_show_form(step_id="mqtt_settings",
            data_schema=vol.Schema({}),
            description_placeholders={
                "connection": "Connected" if connected else "Disconnected",
                "connection_help": help_text,
                "broker": broker,
                "port": port,
                "tls": tls,
                "device_id": self.config_entry.data["device_id"],
                "root": root,
                "mode": "Scoped discovery" if direct_mode(self.hass) else "Native MQTT discovery",
            })

    def _apps(self):
        """Only this PC's HA-owned applications, never old Windows rules."""
        return self.config_entry.options.get("tracked_apps", [])

    def _commit_app_change(self, new_apps):
        """Preserve concurrently changed limits while rejecting app-list races."""
        latest = dict(self.config_entry.options)
        if latest.get("tracked_apps", []) != self._app_baseline:
            return None
        latest["tracked_apps"] = new_apps
        return self.async_create_entry(title="", data=latest)

    async def async_step_tracked_apps(self, user_input=None):
        """Edit list, rename, remove and enroll verified new foreground in ONE form."""
        errors = {}
        if user_input is None:
            try:
                self._app_baseline = list(load_apps(self._apps()).values())
            except ValueError:
                return self.async_abort(reason="invalid_app_configuration")
            # Separate raw identity display from the token-protected Add hint.
            # Both are collected in one short window, never sent to Windows.
            self._selected_app, self._raw_snapshot = await asyncio.gather(
                _discover_foreground_candidate(
                    self.hass, self.config_entry.data["device_id"]),
                _discover_raw_foreground_snapshot(
                    self.hass, self.config_entry.data["device_id"]),
            )
            if not _candidate_matches_raw(self._selected_app, self._raw_snapshot):
                self._selected_app = None
        else:
            # Only the server-side snapshot made when this editor opened
            # may authorize a new application. Never resubscribe on Submit:
            # a parent's explicit choice outlives a child's Alt-Tab/exit.
            try:
                new_apps = apply_app_editor(
                    self._app_baseline, user_input.get("applications"),
                    self._selected_app)
                result = self._commit_app_change(new_apps)
                if result is not None:
                    return result
                errors["base"] = "configuration_changed"
            except ValueError:
                errors["base"] = "invalid_application"

        choices = editor_choices(self._app_baseline, self._selected_app)
        candidate = self._selected_app
        candidate_key = _new_candidate_label(candidate, self._app_baseline)
        raw_value, displayed_as = _raw_foreground_labels(
            self._raw_snapshot, self._app_baseline)

        # HA's native multiple-object editor shows expandable named rows and
        # the built-in Add/Remove-row UI, without a custom frontend dependency.
        options = [{"value": label, "label": label} for label in choices]
        if not options:
            options = [{"value": "__not_detected__", "label": "No foreground candidate"}]
        process_field = {
            "label": "Verified executable / Java signature",
            "required": True,
            "selector": {"select": {"options": options}},
        }
        if candidate_key is not None:
            process_field["default"] = candidate_key

        items = editor_rows(self._app_baseline)
        if user_input is not None and isinstance(user_input.get("applications"), list):
            items = user_input["applications"]
        return self.async_show_form(
            step_id="tracked_apps",
            data_schema=vol.Schema({
                vol.Required("applications", default=items):
                    selector.ObjectSelector(selector.ObjectSelectorConfig(
                        multiple=True, label_field="name",
                        description_field="detected",
                        fields={
                            "name": {
                                "label": "Display name",
                                "required": True,
                                "selector": {"text": {}},
                            },
                            "detected": process_field,
                        },
                    )),
            }),
            description_placeholders={
                "device": self.config_entry.data.get("name")
                          or self.config_entry.data["device_id"],
                "count": str(len(self._app_baseline)),
                "raw_value": raw_value,
                "displayed_as": displayed_as,
            },
            errors=errors,
        )
