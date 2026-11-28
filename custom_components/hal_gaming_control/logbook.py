"""Native Activity / Logbook attribution for Error state transitions."""
from homeassistant.core import callback

from .const import DOMAIN
from .diagnostic_activity import EVENT


@callback
def async_describe_events(hass, async_describe_event):
    """Register our integration event as a recognizable Logbook cause."""
    @callback
    def describe(event):
        data = event.data
        return {
            "name": f"HAL Gaming Control: {data['description']}",
            "message": data["message"],
            "entity_id": data["entity_id"],
        }

    async_describe_event(DOMAIN, EVENT, describe)
