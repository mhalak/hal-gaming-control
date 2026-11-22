"""Admin-only Home Assistant actions for Parent bonus Undo.

The dashboard specifies one concrete HA select entity. No grant ID, Windows
process name, MQTT topic, or arbitrary command is accepted from the browser.
"""
import voluptuous as vol
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN

TARGET_SCHEMA = vol.Schema({vol.Required("entity_id"): cv.entity_id})


def _select_for_call(hass, call):
    user_id = call.context.user_id
    if not user_id:
        # Avoid scheduled automations/anonymous contexts completing Undo.
        raise HomeAssistantError("Undo requires an authenticated HA administrator")
    entity_id = call.data["entity_id"]
    selector = hass.data.get(DOMAIN, {}).get(
        "parent_bonus_undo_selects", {}).get(entity_id)
    if selector is None or not selector.available:
        raise HomeAssistantError("Parent bonus Undo select is unavailable")
    return selector, user_id


@callback
def async_setup_services(hass):
    """Register actions independently of config-entry/device availability."""

    async def prepare(call):
        entity, user_id = _select_for_call(hass, call)
        entity.prepare(user_id)

    async def confirm(call):
        entity, user_id = _select_for_call(hass, call)
        entity.confirm(user_id)

    async_register_admin_service(
        hass, DOMAIN, "prepare_parent_bonus_undo", prepare, TARGET_SCHEMA)
    async_register_admin_service(
        hass, DOMAIN, "confirm_parent_bonus_undo", confirm, TARGET_SCHEMA)
