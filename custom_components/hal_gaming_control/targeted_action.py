"""One-shot, per-device targeted termination shared by UI and custom actions.

The listener owns the expiring capability. Buttons and native HA actions both
consume it through this object; neither may replay the same offer.
"""
import json
import secrets
from time import monotonic, time

from homeassistant.components import mqtt
from homeassistant.exceptions import HomeAssistantError

from .const import ROOT
from .targeted_protocol import parse_offer, offer_matches_raw


class TargetedTermination:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.root = f"{ROOT}/{coordinator.device_id}"
        self.offer = None
        self.offered_at = None
        self._unsubscribe = None

    async def async_start(self):
        self._unsubscribe = await mqtt.async_subscribe(
            self.coordinator.hass, self.root + "/state/terminate_offer",
            self._on_offer, qos=0)

    def _on_offer(self, message):
        try:
            self.offer = parse_offer(
                message.topic, message.payload, self.coordinator.device_id,
                retained=getattr(message, "retain", None), now=time())
            self.offered_at = monotonic()
        except (ValueError, TypeError):
            self.offer = None
            self.offered_at = None
        self.coordinator.async_update_listeners()

    @property
    def available(self):
        c = self.coordinator
        if (self.offer is None or self.offered_at is None
                or c.foreground is None or not mqtt.is_connected(c.hass)
                or not c.storage_healthy):
            return False
        source = c.foreground
        if source.current() in (None, "idle"):
            return False
        return offer_matches_raw(
            self.offer, source.last_raw, now=monotonic(),
            offered_at=self.offered_at, tracked=source.ledger.apps)

    async def async_terminate(self):
        if not self.available:
            raise HomeAssistantError("No fresh verified tracked game to terminate")
        offer = self.offer
        # Consume before first await; button and native action are one-use.
        self.offer = None
        self.offered_at = None
        self.coordinator.async_update_listeners()
        await mqtt.async_publish(
            self.coordinator.hass, self.root + "/command/terminate_target",
            json.dumps({
                "version": 1, "device_id": self.coordinator.device_id,
                "epoch": offer["epoch"], "token": offer["token"],
                "request_id": secrets.token_hex(16),
            }),
            qos=0, retain=False)

    def close(self):
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.offer = None
        self.offered_at = None
