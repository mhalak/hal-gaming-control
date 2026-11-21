"""Gaming presence/activity legacy binary sensors retired after v2 cutover.

The retained Windows wire protocol is not a valid HA foreground source.
Future HA restriction sensors will derive from verified coordinator totals.
"""


async def async_setup_entry(hass, entry, async_add_entities):
    """There are no legacy binary sensors to register."""
