"""Device-scoped native Home Assistant actions (no button.press wrappers)."""
import math
import re

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .const import DOMAIN, ROOT
from .smart_parent_control import async_add_smart_bonus


def _strict_int(value):
    if type(value) is not int:
        raise vol.Invalid("Expected an integer")
    return value


def _strict_bool(value):
    if type(value) is not bool:
        raise vol.Invalid("Expected true or false")
    return value


def _bounded_text(max_length):
    def validate(value):
        if (type(value) is not str or not 0 < len(value.strip()) <= max_length
                or any(ord(ch) < 32 for ch in value)):
            raise vol.Invalid("Invalid plain text")
        return value
    return validate


def _button_id(value):
    if type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,31}", value) is None:
        raise vol.Invalid("Invalid button identifier")
    return value


def _percent(value):
    if (type(value) not in (float, int) or not math.isfinite(value)
            or not 0 <= value <= 100):
        raise vol.Invalid("Progress must be a finite percentage from 0 to 100")
    return value


DEVICE = {vol.Required("device_id"): cv.string}
BUTTON = vol.Schema({
    vol.Required("id"): _button_id,
    vol.Required("text"): _bounded_text(48),
    vol.Required("color"): vol.In(("neutral", "primary", "success", "warning", "danger")),
}, extra=vol.PREVENT_EXTRA)
SCHEMA_LOCK = vol.Schema(DEVICE, extra=vol.PREVENT_EXTRA)
SCHEMA_TERMINATE = vol.Schema(DEVICE, extra=vol.PREVENT_EXTRA)
SCHEMA_BONUS = vol.Schema(DEVICE | {
    vol.Required("minutes"): vol.All(_strict_int, vol.Range(min=1, max=600)),
}, extra=vol.PREVENT_EXTRA)
SCHEMA_UNLIMITED = vol.Schema(DEVICE | {
    vol.Required("enabled"): _strict_bool,
}, extra=vol.PREVENT_EXTRA)
_SCHEMA_POPUP_FIELDS = vol.Schema(DEVICE | {
    vol.Optional("operation", default="upsert"): vol.In(("upsert", "hide")),
    vol.Optional("heading"): _bounded_text(100),
    vol.Optional("description"): _bounded_text(120),
    vol.Optional("remaining_seconds"): vol.All(_strict_int, vol.Range(min=0, max=604800)),
    vol.Optional("progress_percent"): _percent,
    vol.Optional("buttons"): vol.All([BUTTON], vol.Length(max=3)),
}, extra=vol.PREVENT_EXTRA)


_POPUP_VIEW_FIELDS = frozenset((
    "heading", "description", "remaining_seconds", "progress_percent", "buttons",
))


def _ignore_hidden_view_fields(value):
    """Hide is independent of stale values in the shared action form."""
    if isinstance(value, dict) and value.get("operation") == "hide":
        return {key: val for key, val in value.items()
                if key not in _POPUP_VIEW_FIELDS}
    return value


SCHEMA_POPUP = vol.Schema(vol.All(_ignore_hidden_view_fields, _SCHEMA_POPUP_FIELDS))


def _coordinator(hass, device_id):
    """Resolve the actual HA device registry ID; forbid implicit broadcast."""
    _, entry = service.async_get_device_and_config_entry(hass, DOMAIN, device_id)
    coordinator = entry.runtime_data
    if coordinator is None or coordinator.device_id != entry.data.get("device_id"):
        raise ServiceValidationError("Gaming PC config entry is not loaded")
    return coordinator


@callback
def async_setup_services(hass):
    """Actions exist even before any device/config entry has loaded."""

    async def async_lock_pc(call):
        c = _coordinator(hass, call.data["device_id"])
        if ("lock_pc" not in c.advertised or c.foreground is None
                or not mqtt.is_connected(hass) or c.foreground.current() is None):
            raise HomeAssistantError("Gaming PC is offline, stale or cannot lock")
        await mqtt.async_publish(
            hass, f"{ROOT}/{c.device_id}/command/lock_pc",
            "PRESS", qos=0, retain=False)

    async def async_terminate_game(call):
        c = _coordinator(hass, call.data["device_id"])
        await c.termination.async_terminate()

    async def async_add_bonus(call):
        c = _coordinator(hass, call.data["device_id"])
        await async_add_smart_bonus(hass, c, call.data["minutes"])

    async def async_set_unlimited(call):
        c = _coordinator(hass, call.data["device_id"])
        enabled = call.data["enabled"]
        if bool(c.options["unlimited"]) != enabled:
            updated = dict(c.entry.options) | {"unlimited": enabled}
            if hass.config_entries.async_update_entry(c.entry, options=updated) is False:
                raise HomeAssistantError("Unlimited gaming setting was not saved")

    async def async_popup(call):
        c = _coordinator(hass, call.data["device_id"])
        options = call.data
        operation = options["operation"]
        fields = ("heading", "remaining_seconds", "progress_percent")
        if operation == "upsert" and any(key not in options for key in fields):
            raise ServiceValidationError(
                "Popup upsert requires heading, remaining_seconds and progress_percent")
        if operation == "hide":
            await c.popup.async_send("hide")
            return
        buttons = options.get("buttons", [])
        if len({b["id"] for b in buttons}) != len(buttons):
            raise ServiceValidationError("Popup button IDs must be unique")
        await c.popup.async_send(
            operation,
            heading=options.get("heading"),
            description=options.get("description", ""),
            remaining_seconds=options.get("remaining_seconds"),
            progress_percent=options.get("progress_percent"),
            buttons=buttons)

    for name, handler, schema in (
        ("lock_pc", async_lock_pc, SCHEMA_LOCK),
        ("terminate_game", async_terminate_game, SCHEMA_TERMINATE),
        ("add_bonus", async_add_bonus, SCHEMA_BONUS),
        ("set_unlimited", async_set_unlimited, SCHEMA_UNLIMITED),
        ("popup", async_popup, SCHEMA_POPUP),
    ):
        service.async_register_admin_service(
            hass, DOMAIN, name, handler, schema=schema)
