"""Independent diagnostic for the last reported Windows agent version."""
import json
from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory
from .const import ROOT
from .entity import GamingEntity
from .protocol import parse_discovery
from .update_protocol import version_tuple


class AgentVersionSensor(GamingEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:tag-outline"
    _attr_native_value = None
    _attr_extra_state_attributes = {"version_source": "last_reported"}

    def __init__(self, coordinator):
        super().__init__(coordinator, "agent_version", "Windows agent version")
        self.topic = f"{ROOT}/{coordinator.device_id}/discovery"

    @property
    def available(self):
        # Retained metadata describes the last reported installation, not
        # whether the PC is currently online. Keep it useful while offline.
        return True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(await mqtt.async_subscribe(
            self.hass, self.topic, self._metadata, qos=1))

    @callback
    def _metadata(self, message):
        if message.topic != self.topic:
            return
        try:
            if not isinstance(message.payload, (str, bytes)) or len(message.payload) > 65536:
                raise ValueError("Invalid metadata")
            parse_discovery(message.topic, message.payload)
            version = json.loads(message.payload)["agent_version"]
            version_tuple(version)
        except (ValueError, TypeError, KeyError):
            version = None
        self._attr_native_value = version
        self.async_write_ha_state()
