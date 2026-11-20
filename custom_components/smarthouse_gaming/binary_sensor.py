"""Expose process presence and foreground activity in direct MQTT mode."""
from .direct_mqtt import DirectInGame, DirectGamingActive


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    if c.direct:
        async_add_entities([DirectInGame(c), DirectGamingActive(c)])
