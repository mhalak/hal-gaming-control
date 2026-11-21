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
from .const import DEFAULTS, DOMAIN, ROOT
from .candidate_protocol import parse_candidate
from .app_registry import add_app, identity_key, load_apps, rename_app, remove_app
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
                "tracked_apps": "Tracked applications",
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
        """Read only this device's HA-owned mappings, not Windows discovery."""
        return list(self.config_entry.options.get("tracked_apps", []))

    def _app_choices(self, apps):
        return [
            {"value": key,
             "label": f"{row['name']} — {row['process']}"
                      + (f" + {row['signature']['value']}" if row['signature'] else "")}
            for key, row in load_apps(apps).items()
        ]

    def _commit_app_change(self, new_apps):
        """Commit app edits without replacing concurrent limit/budget options."""
        latest = dict(self.config_entry.options)
        if latest.get("tracked_apps", []) != self._app_baseline:
            return None
        latest["tracked_apps"] = new_apps
        return self.async_create_entry(title="", data=latest)

    async def async_step_tracked_apps(self, user_input=None):
        """HA-owned app configuration: all edits remain local to selected entry."""
        apps = self._apps()
        try:
            tracked = load_apps(apps)
        except ValueError:
            return self.async_abort(reason="invalid_app_configuration")
        # Refresh only on opening the menu, not when submitting edits.
        candidate = await _discover_foreground_candidate(
            self.hass, self.config_entry.data["device_id"])
        self._shown_candidate = candidate
        if candidate:
            raw = candidate["process"]
            signature = candidate.get("signature")
            if signature:
                raw += f" + {signature['kind']}: {signature['value']}"
            elif raw.casefold() in ("java.exe", "javaw.exe"):
                raw += " (ambiguous Java runtime)"
        else:
            raw = "No fresh foreground application detected"
        display = "\n".join(
            f"• {row['name']} ← {row['process']}"
            + (f" + {row['signature']['value']}" if row['signature'] else "")
            for row in tracked.values()
        ) or "No HA-managed applications configured yet."
        return self.async_show_menu(
            step_id="tracked_apps",
            menu_options={"add_app": "Add application",
                          "rename_app": "Rename application",
                          "remove_app": "Remove application",
                          "menu": "Back"},
            description_placeholders={
                "device": self.config_entry.data.get("name") or self.config_entry.data["device_id"],
                "count": str(len(tracked)),
                "apps": display,
                "legacy_apps": "\n".join(
                    f"• {name}" for name in self.config_entry.data.get("games", []))
                    or "None reported by legacy agent",
                "candidate": raw,
            },
        )

    async def async_step_add_app(self, user_input=None):
        """Bind an alias to the unchanged live candidate, never stored on PC."""
        errors = {}
        if user_input is None:
            self._selected_app = await _discover_foreground_candidate(
                self.hass, self.config_entry.data["device_id"])
            self._app_baseline = self._apps()
        else:
            selected = getattr(self, "_selected_app", None)
            current = await _discover_foreground_candidate(
                self.hass, self.config_entry.data["device_id"])
            if (selected is None or current is None
                    or any(current.get(k) != selected.get(k)
                           for k in ("process", "signature", "token"))):
                errors["base"] = "candidate_changed"
            else:
                try:
                    next_apps = add_app(self._app_baseline, selected, user_input["name"])
                    result = self._commit_app_change(next_apps)
                    if result is not None:
                        return result
                    errors["base"] = "configuration_changed"
                except ValueError:
                    errors["base"] = "invalid_application"
        selected = getattr(self, "_selected_app", None)
        valid = False
        if selected:
            try:
                identity_key(selected["process"], selected.get("signature"))
                valid = True
            except ValueError:
                pass
        if not valid:
            errors["base"] = "no_live_candidate"
        description = " + ".join(
            [selected["process"]]
            + ([selected["signature"]["value"]] if selected and selected.get("signature") else [])
        ) if valid else "No uniquely identifiable foreground application"
        return self.async_show_form(
            step_id="add_app",
            data_schema=vol.Schema({vol.Required("name"): str}) if valid else vol.Schema({}),
            description_placeholders={"candidate": description},
            errors=errors,
        )

    async def async_step_rename_app(self, user_input=None):
        """Rename a stable process signature without losing usage identity."""
        errors = {}
        if user_input is None:
            self._app_baseline = self._apps()
        elif "target" in user_input:
            try:
                next_apps = rename_app(
                    self._app_baseline, user_input["target"], user_input["name"])
                result = self._commit_app_change(next_apps)
                if result is not None:
                    return result
                errors["base"] = "configuration_changed"
            except ValueError:
                errors["base"] = "invalid_application"
        try:
            choices = self._app_choices(self._app_baseline)
        except ValueError:
            return self.async_abort(reason="invalid_app_configuration")
        if not choices:
            return self.async_show_form(
                step_id="rename_app", data_schema=vol.Schema({}),
                errors={"base": "no_tracked_apps"})
        return self.async_show_form(
            step_id="rename_app",
            data_schema=vol.Schema({
                vol.Required("target"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=choices)),
                vol.Required("name"): str,
            }),
            errors=errors,
        )

    async def async_step_remove_app(self, user_input=None):
        """Remove selected HA mapping only; never send device commands."""
        errors = {}
        if user_input is None:
            self._app_baseline = self._apps()
        elif "target" in user_input:
            try:
                next_apps = remove_app(self._app_baseline, user_input["target"])
                result = self._commit_app_change(next_apps)
                if result is not None:
                    return result
                errors["base"] = "configuration_changed"
            except ValueError:
                errors["base"] = "invalid_application"
        try:
            choices = self._app_choices(self._app_baseline)
        except ValueError:
            return self.async_abort(reason="invalid_app_configuration")
        if not choices:
            return self.async_show_form(
                step_id="remove_app", data_schema=vol.Schema({}),
                errors={"base": "no_tracked_apps"})
        return self.async_show_form(
            step_id="remove_app",
            data_schema=vol.Schema({
                vol.Required("target"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=choices)),
            }),
            errors=errors,
        )

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
        # A separate HA-only CRUD flow may have saved app aliases meanwhile.
        # Never let an unrelated Limits/Save flow overwrite those mappings.
        if "tracked_apps" in latest:
            self.values["tracked_apps"] = latest["tracked_apps"]
        else:
            self.values.pop("tracked_apps", None)
        for key in ("bonus_date", "bonus_minutes"):
            self.values.pop(key, None)
            if key in latest:
                self.values[key] = latest[key]
        self.values["actions"] = list(latest["actions"])
        return self.async_create_entry(title="", data=self.values)
