"""Scoped MQTT telemetry and controls for HA installations with discovery disabled."""
import json

from homeassistant.components import mqtt
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory

from .const import ROOT
from .action_registry import ACTION_REGISTRY
from .protocol import parse_discovery


def direct_mode(hass):
    entries = hass.config_entries.async_entries("mqtt")
    # Match the MQTT integration's merged config, not discovery-source of the PC.
    return bool(entries and not (dict(entries[0].data) | dict(entries[0].options)).get("discovery", True))


class DirectEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, key, name, state_key=None):
        self._root = f"{ROOT}/{coordinator.device_id}"
        self._key = key
        self._state_key = state_key
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={("mqtt", f"smarthouse_gaming_{coordinator.device_id}")},
            name=coordinator.entry.data["name"], manufacturer="SmartHouse",
            model="Windows Gaming Agent")
        self._connected = False
        self._online = False
        self._value = None

    @property
    def available(self):
        return self._connected and self._online and (self._state_key is None or self._value is not None)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._connected = mqtt.is_connected(self.hass)
        self.async_on_remove(mqtt.async_subscribe_connection_status(self.hass, self._connection))
        self.async_on_remove(await mqtt.async_subscribe(self.hass, self._root + "/availability", self._availability, qos=1))
        if self._state_key:
            self.async_on_remove(await mqtt.async_subscribe(self.hass, self._root + "/state/" + self._state_key, self._state, qos=1))

    @callback
    def _connection(self, connected):
        self._connected = connected
        if not connected:
            self._online = False
            self._value = None
        self.async_write_ha_state()

    @callback
    def _availability(self, message):
        self._online = message.payload == "online"
        if not self._online:
            self._value = None
        self.async_write_ha_state()

    @callback
    def _state(self, message):
        value = message.payload
        if self._state_key == "uptime":
            if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 16:
                value = int(value)
            else:
                value = None
        elif self._state_key == "in_game":
            value = {"ON": True, "OFF": False}.get(value) if isinstance(value, str) else None
        elif not isinstance(value, str) or not value or len(value) > 255 or value in ("unknown", "unavailable"):
            value = None
        self._value = value
        self.async_write_ha_state()


class DirectUptime(DirectEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, c):
        super().__init__(c, "uptime", "Uptime", "uptime")

    @property
    def native_value(self):
        return self._value


class DirectCurrentGame(DirectEntity, SensorEntity):
    def __init__(self, c):
        super().__init__(c, "current_game", "Current game", "current_game")

    @property
    def native_value(self):
        return self._value


class DirectInGame(DirectEntity, BinarySensorEntity):
    def __init__(self, c):
        super().__init__(c, "in_game", "In game", "in_game")

    @property
    def is_on(self):
        return self._value


class DirectForeground(DirectEntity):
    """Read the complete scoped foreground pair, never infer it from process presence."""

    def __init__(self, c, key, name):
        super().__init__(c, key, name)
        self._supported = False
        self._focus_online = False
        self._game = None
        self._active = None
        self._games = set(c.games)

    @property
    def available(self):
        return (self._connected and self._online and self._supported and self._focus_online
                and ((self._active is True and self._game in self._games)
                     or (self._active is False and self._game == "idle")))

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        callbacks = {
            "/discovery": self._metadata,
            "/state/focus_availability": self._focus,
            "/state/active_game": self._foreground_game,
            "/state/gaming_active": self._foreground_active,
        }
        for suffix, handler in callbacks.items():
            self.async_on_remove(await mqtt.async_subscribe(
                self.hass, self._root + suffix, handler, qos=1))

    def _clear_pair(self):
        self._game = self._active = None

    @callback
    def _connection(self, connected):
        if not connected:
            self._supported = self._focus_online = False
            self._clear_pair()
        super()._connection(connected)

    @callback
    def _availability(self, message):
        if message.payload != "online":
            self._focus_online = False
            self._clear_pair()
        super()._availability(message)

    @callback
    def _metadata(self, message):
        try:
            if (message.topic != self._root + "/discovery"
                    or not isinstance(message.payload, (str, bytes))
                    or len(message.payload) > 65536):
                raise ValueError("Invalid foreground metadata")
            parse_discovery(message.topic, message.payload)
            version = json.loads(message.payload).get("focus_protocol")
            supported = type(version) is int and version == 1
        except (ValueError, TypeError):
            supported = False
        self._supported = supported
        if not supported:
            self._focus_online = False
            self._clear_pair()
        self.async_write_ha_state()

    @callback
    def _focus(self, message):
        self._focus_online = message.payload == "online"
        if not self._focus_online:
            self._clear_pair()
        self.async_write_ha_state()

    @callback
    def _foreground_game(self, message):
        value = message.payload
        self._game = value if isinstance(value, str) and (value == "idle" or value in self._games) else None
        self.async_write_ha_state()

    @callback
    def _foreground_active(self, message):
        value = message.payload
        self._active = {"ON": True, "OFF": False}.get(value) if isinstance(value, str) else None
        self.async_write_ha_state()


class DirectActiveGame(DirectForeground, SensorEntity):
    def __init__(self, c):
        super().__init__(c, "active_game", "Active game")

    @property
    def native_value(self):
        return self._game if self.available else None


class DirectGamingActive(DirectForeground, BinarySensorEntity):
    def __init__(self, c):
        super().__init__(c, "gaming_active", "Gaming active")

    @property
    def is_on(self):
        return self._active if self.available else None


class DirectAction(DirectEntity, ButtonEntity):
    def __init__(self, c, action):
        if action not in ACTION_REGISTRY:
            raise ValueError("Unsupported gaming action")
        super().__init__(c, action, ACTION_REGISTRY[action].label)

    async def async_press(self):
        if not self.available or not mqtt.is_connected(self.hass):
            raise HomeAssistantError("Gaming PC unavailable")
        await mqtt.async_publish(self.hass, self._root + "/command/" + ACTION_REGISTRY[self._key].topic,
                                 "PRESS", qos=0, retain=False)
