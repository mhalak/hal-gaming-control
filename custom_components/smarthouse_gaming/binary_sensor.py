"""Passive, HA-owned gaming restriction signal.

This entity evaluates policy only. It never publishes MQTT commands.
Unverified, missing, or stale foreground accounting must not become "off".
"""

from math import isfinite

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.util import dt as dt_util

from .entity import GamingEntity
from .rule_engine import violations


def _valid_seconds(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def _has_verified_policy_data(data):
    """Require authoritative day/week totals and the current active-game scope."""
    if not isinstance(data, dict) or data.get("ready") is not True:
        return False
    totals = data.get("totals")
    active = data.get("active")
    if not isinstance(totals, dict) or not isinstance(active, (list, tuple)):
        return False
    per_game = totals.get("per_game")
    if (not isinstance(per_game, dict)
            or not all(_valid_seconds(totals.get(key)) for key in ("daily", "weekly"))
            or not all(isinstance(game, str) and game in per_game
                       and _valid_seconds(per_game[game]) for game in active)):
        return False
    # v2 foreground snapshots always supply a matching friendly active-game
    # name. An inconsistent MQTT transition is not a valid restriction signal.
    if "active_game" in data:
        current = data["active_game"]
        if not (current == "idle" and not active
                or isinstance(current, str) and current != "idle"
                and list(active) == [current]):
            return False
    return True


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([GamingRestriction(entry.runtime_data)])


class GamingRestriction(GamingEntity, BinarySensorEntity):
    """ON when a verified budget/schedule/per-game restriction applies."""

    _attr_icon = "mdi:gamepad-off-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "gaming_restriction", "Gaming restriction")

    @property
    def available(self):
        data = self.coordinator.data or {}
        return _has_verified_policy_data(data) and super().available

    def _reasons(self):
        if not self.available:
            return None
        data = self.coordinator.data
        return violations(self.coordinator.options, data["totals"],
                          dt_util.now(), data["active"])

    @property
    def is_on(self):
        reasons = self._reasons()
        return bool(reasons) if reasons is not None else None

    @property
    def extra_state_attributes(self):
        reasons = self._reasons()
        return {"reasons": reasons,
                "reason": reasons[0] if reasons else None}
