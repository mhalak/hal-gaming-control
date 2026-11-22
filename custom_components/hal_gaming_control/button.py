"""Manual actions and a local daily budget bonus."""
import json
import secrets
from time import monotonic, time

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from .direct_mqtt import DirectAction
from .action_registry import ACTION_REGISTRY
from .entity import GamingEntity
from .rule_engine import effective_daily
from .parent_bonus import add_parent_grant
from .const import ROOT
from .targeted_protocol import parse_offer, offer_matches_raw

BONUS_INCREMENT = 30


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [AddDailyBudget(c), TerminateTrackedGame(c)]
    if c.direct:
        entities.extend(DirectAction(c, key) for key in ACTION_REGISTRY if key in c.advertised)
    async_add_entities(entities)


class AddDailyBudget(GamingEntity, ButtonEntity):
    _attr_icon = "mdi:timer-plus-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "add_daily_budget", "Add 30 minutes")

    @property
    def available(self):
        return True

    async def async_press(self):
        now = dt_util.now()
        options = self.coordinator.options
        if effective_daily(options, now.weekday() >= 5) < 0:
            raise HomeAssistantError("Set a finite daily limit before adding time")
        entry = self.coordinator.entry
        self.hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {
            "bonus_date": now.date().isoformat(),
            "bonus_minutes": daily_bonus_minutes(options, now) + BONUS_INCREMENT,
        })


class TerminateTrackedGame(GamingEntity, ButtonEntity):
    """HA-owned manual action; never a background quota-enforcement command."""

    _attr_icon = "mdi:close-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "terminate_tracked_game", "Terminate active game")
        self._root = f"{ROOT}/{coordinator.device_id}"
        self._offer = None
        self._offered_at = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(await mqtt.async_subscribe(
            self.hass, self._root + "/state/terminate_offer",
            self._observe_offer, qos=0))

    @property
    def available(self):
        if not super().available or self._offer is None or not mqtt.is_connected(self.hass):
            return False
        source = self.coordinator.foreground
        if source is None or source.current() in (None, "idle"):
            return False
        return offer_matches_raw(
            self._offer, source.last_raw, now=monotonic(),
            offered_at=self._offered_at, tracked=source.ledger.apps)

    def _observe_offer(self, message):
        try:
            self._offer = parse_offer(
                message.topic, message.payload, self.coordinator.device_id,
                retained=getattr(message, "retain", None), now=time())
            self._offered_at = monotonic()
        except (ValueError, TypeError):
            self._offer = None
            self._offered_at = None
        self.async_write_ha_state()

    async def async_press(self):
        if not self.available:
            raise HomeAssistantError("No fresh verified tracked game to terminate")
        offer = self._offer
        # Consume before publishing: repeated UI clicks cannot replay a token.
        self._offer = None
        self._offered_at = None
        self.async_write_ha_state()
        await mqtt.async_publish(
            self.hass, self._root + "/command/terminate_target",
            json.dumps({"version": 1, "device_id": self.coordinator.device_id,
                        "epoch": offer["epoch"], "token": offer["token"],
                        "request_id": secrets.token_hex(16)}),
            qos=0, retain=False)
