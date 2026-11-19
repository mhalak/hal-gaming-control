"""Native action builder controls; selecting an action configures, never invokes it."""
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from .action_registry import ACTION_REGISTRY, available_actions, selected_actions
from .entity import GamingEntity

PLACEHOLDER = "Select action"


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ActionSelector(entry.runtime_data, True),
                        ActionSelector(entry.runtime_data, False)])


class ActionSelector(GamingEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, adding):
        super().__init__(coordinator, "add_action" if adding else "remove_action",
                         "Add action" if adding else "Remove action")
        self.adding = adding
        self._attr_icon = "mdi:playlist-plus" if adding else "mdi:playlist-minus"

    @property
    def available(self):
        return True

    @property
    def selected(self):
        return selected_actions(self.coordinator.advertised, self.coordinator.options["actions"])

    @property
    def choices(self):
        return available_actions(self.coordinator.advertised, self.selected) if self.adding else self.selected

    @property
    def options(self):
        return [PLACEHOLDER] + [ACTION_REGISTRY[key].label for key in self.choices]

    @property
    def current_option(self):
        return PLACEHOLDER

    @property
    def extra_state_attributes(self):
        return {"configured_actions": [ACTION_REGISTRY[key].label for key in self.selected]}

    async def async_select_option(self, option):
        if option == PLACEHOLDER:
            return
        key = next((key for key in self.choices if ACTION_REGISTRY[key].label == option), None)
        if key is None:
            raise HomeAssistantError("Action is not currently selectable")
        actions = self.selected
        if self.adding:
            actions.append(key)
        else:
            actions.remove(key)
        entry = self.coordinator.entry
        self.hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {"actions": actions})
        self.async_write_ha_state()
