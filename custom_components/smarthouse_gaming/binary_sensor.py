"""Expose only the raw in-game signal in direct MQTT mode."""
from .direct_mqtt import DirectInGame


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    if c.direct:
        async_add_entities([DirectInGame(c)])
