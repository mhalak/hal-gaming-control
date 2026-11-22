from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

class GamingEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_name = name
        # Use the same device identifier as the native MQTT discovery entities.
        self._attr_device_info = DeviceInfo(
            identifiers={("mqtt", f"smarthouse_gaming_{coordinator.device_id}")},
            name=coordinator.entry.data["name"], manufacturer="SmartHouse",
            model="Windows Gaming Agent")

    @property
    def available(self):
        return super().available and bool(self.coordinator.data.get("ready"))
