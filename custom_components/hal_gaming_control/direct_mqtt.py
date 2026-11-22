"""Scoped MQTT telemetry and controls for HA installations with discovery disabled."""
from time import monotonic, time

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory

from .const import ROOT
from .action_registry import ACTION_REGISTRY
from .protocol import parse_discovery
from .unified_telemetry import TelemetryOrder, decode_telemetry, MAX_AGE


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
        elif not isinstance(value, str) or not value or len(value) > 255 or value in ("unknown", "unavailable"):
            value = None
        self._value = value
        self.async_write_ha_state()


class DirectUptime(DirectEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, c):
        self._unified = c.entry.options.get("unified_telemetry_enabled") is True
        super().__init__(c, "uptime", "Uptime",
                         None if self._unified else "uptime")
        self._order = TelemetryOrder() if self._unified else None
        self._seen_at = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self._unified:
            self.async_on_remove(await mqtt.async_subscribe(
                self.hass, self._root + "/state/telemetry",
                self._v3_telemetry, qos=0))

    @callback
    def _connection(self, connected):
        if self._order is not None and connected is not True:
            self._order.suspend()
            self._seen_at = None
        super()._connection(connected)

    @callback
    def _availability(self, message):
        if self._order is not None and message.payload not in ("online", b"online"):
            self._order.suspend()
            self._seen_at = None
        super()._availability(message)

    @callback
    def _v3_telemetry(self, message):
        if not self._connected or not self._online:
            return
        now, mono = time(), monotonic()
        if message.topic != self._root + "/state/telemetry":
            return
        try:
            packet = decode_telemetry(
                message.payload, self._root.rsplit("/", 1)[-1],
                retained=getattr(message, "retain", None), wall_now=now)
        except (ValueError, TypeError, RecursionError):
            self._value = None
            self._seen_at = None
            self.async_write_ha_state()
            return
        if not self._order.accept(packet, monotonic_now=mono):
            return
        self._value = packet["system"]["uptime_seconds"]
        self._seen_at = mono
        self.async_write_ha_state()

    @property
    def available(self):
        if not super().available:
            return False
        return (not self._unified or (self._value is not None
                and self._seen_at is not None
                and 0 <= monotonic() - self._seen_at < MAX_AGE))

    @property
    def native_value(self):
        return self._value


class DirectAction(DirectEntity, ButtonEntity):
    def __init__(self, c, action):
        if action not in ACTION_REGISTRY:
            raise ValueError("Unsupported gaming action")
        super().__init__(c, action, ACTION_REGISTRY[action].label)
        # Old entries can retain the legacy terminate capability after the
        # agent migrates to an empty game catalog. Require fresh agent metadata.
        self._terminate_capable = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self._key == "terminate_game":
            self.async_on_remove(await mqtt.async_subscribe(
                self.hass, self._root + "/discovery", self._capabilities, qos=1))

    @callback
    def _capabilities(self, message):
        if message.topic != self._root + "/discovery":
            return
        try:
            metadata = parse_discovery(message.topic, message.payload)
            self._terminate_capable = (
                bool(metadata["games"]) and "terminate_game" in metadata["actions"])
        except (ValueError, TypeError, KeyError):
            self._terminate_capable = False
        self.async_write_ha_state()

    @property
    def available(self):
        return (super().available and
                (self._key != "terminate_game" or self._terminate_capable))

    async def async_press(self):
        if not self.available or not mqtt.is_connected(self.hass):
            raise HomeAssistantError("Gaming PC unavailable")
        await mqtt.async_publish(self.hass, self._root + "/command/" + ACTION_REGISTRY[self._key].topic,
                                 "PRESS", qos=0, retain=False)
