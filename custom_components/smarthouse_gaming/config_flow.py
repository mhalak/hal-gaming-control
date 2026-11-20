"""Native Config / Options Flow with manual-action ownership."""
import asyncio
import logging
import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import DEFAULTS, DOMAIN, ROOT
from .direct_mqtt import direct_mode
from .protocol import parse_discovery
from .update_protocol import catalog_url
from datetime import time

_LOGGER = logging.getLogger(__name__)

# The user step listens only for this bounded window; retained discovery payloads arrive immediately.
DISCOVERY_WINDOW = 3.0
DISCOVERY_FILTER = "SmartHouse/Gaming/+/discovery"
MAX_DISCOVERY_PAYLOAD = 65536


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
    """Read only the broker address and port from HA's shared MQTT entry.

    Never return credentials, connection URLs, or arbitrary untrusted strings.
    HA's native MQTT reconfigure flow owns all edits and TLS configuration.
    """
    entries = hass.config_entries.async_entries("mqtt")
    if not entries:
        return "Not configured", "Unknown"
    if len(entries) != 1:
        return "Not available", "Unknown"
    data = entries[0].data
    raw = data.get("broker")
    broker = (raw if isinstance(raw, str)
              and re.fullmatch(r"[A-Za-z0-9_.:\-\[\]]{1,255}", raw)
              else "Not available")
    port = data.get("port")
    port_label = str(port) if type(port) is int and 1 <= port <= 65535 else "Unknown"
    return broker, port_label


class GamingOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        self.values = DEFAULTS | dict(self.config_entry.options)
        self.values.pop("unlimited", None)
        self.values.pop("weekend_total", None)
        self.reset_limits = set()
        return await self.async_step_menu()

    async def async_step_menu(self, user_input=None):
        # Legacy automatic actions are preserved for reversible migration, never edited here.
        menu = {"limits": "Restrictions and schedule",
                "mqtt_settings": "MQTT configuration",
                "update_settings": "Windows update settings",
                "save": "Save"}
        return self.async_show_menu(step_id="menu", menu_options=menu)

    async def async_step_limits(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                for key in ("schedule_start", "schedule_end"):
                    value = time.fromisoformat(user_input[key])
                    if value.tzinfo is not None:
                        raise ValueError
                self.reset_limits = {key for key in ("daily", "weekly", "weekend_daily")
                                     if user_input.get("reset_" + key, False)}
                self.values.update({k: v for k, v in user_input.items() if not k.startswith("reset_")})
                return await self.async_step_menu()
            except ValueError:
                errors["base"] = "invalid_time"
        schema = {vol.Required(key, default=self.values[key]): bool for key in ("enabled", "schedule_enabled")}
        for key in ("daily", "weekly", "weekend_daily"):
            schema[vol.Optional("reset_" + key, default=key in self.reset_limits)] = bool
        for key in ("schedule_start", "schedule_end"):
            schema[vol.Required(key, default=self.values[key])] = str
        return self.async_show_form(step_id="limits", data_schema=vol.Schema(schema), errors=errors)

    async def async_step_mqtt_settings(self, user_input=None):
        """Show the shared connection and per-device topics without exposing secrets."""
        if user_input is not None:
            return await self.async_step_menu()
        root = f"{ROOT}/{self.config_entry.data['device_id']}"
        broker, port = _mqtt_broker_details(self.hass)
        return self.async_show_form(step_id="mqtt_settings",
            data_schema=vol.Schema({}),
            description_placeholders={
                "connection": "Connected" if mqtt.is_connected(self.hass) else "Disconnected",
                "broker": broker,
                "port": port,
                "device_id": self.config_entry.data["device_id"],
                "root": root,
                "mode": "Scoped discovery" if direct_mode(self.hass) else "Native MQTT discovery",
            })

    async def async_step_update_settings(self, user_input=None):
        errors = {}
        if user_input is not None:
            value = user_input["update_catalog_url"].strip()
            try:
                if value:
                    catalog_url(value)
                self.values["update_catalog_url"] = value
                return await self.async_step_menu()
            except ValueError:
                errors["base"] = "invalid_catalog"
        return self.async_show_form(step_id="update_settings", data_schema=vol.Schema({
            vol.Required("update_catalog_url", default=self.values.get("update_catalog_url", "")): str
        }), errors=errors)

    async def async_step_save(self, user_input=None):
        # Preserve live device controls changed while the options UI was open.
        latest = DEFAULTS | dict(self.config_entry.options)
        for key in ("daily", "weekly", "weekend_daily"):
            self.values[key] = -1 if key in self.reset_limits else latest[key]
        self.values["unlimited"] = latest["unlimited"]
        # The per-game editor is temporarily withdrawn. Do not overwrite legacy
        # data or concurrent changes when saving unrelated settings.
        self.values["per_game"] = dict(latest["per_game"])
        for key in ("bonus_date", "bonus_minutes"):
            self.values.pop(key, None)
            if key in latest:
                self.values[key] = latest[key]
        self.values["actions"] = list(latest["actions"])
        return self.async_create_entry(title="", data=self.values)
