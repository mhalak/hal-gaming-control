"""Restriction signal contract: native HA, data safety, bonuses and passive actions."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.smarthouse_gaming.binary_sensor import GamingRestriction
from custom_components.smarthouse_gaming.const import DEFAULTS
from custom_components.smarthouse_gaming.switch import GamingRulesSwitch


TZ = ZoneInfo("Europe/Zagreb")


def at(day, hour=12):
    return datetime(2026, 11, day, hour, tzinfo=TZ)


class StubCoordinator:
    def __init__(self, *, options=None, data=None, device_id="pc1"):
        self.device_id = device_id
        self.entry = SimpleNamespace(data={"name": "Gaming PC"}, options=dict(options or {}))
        self.last_update_success = True
        self.options = DEFAULTS | (options or {})
        self.data = data if data is not None else {
            "ready": True, "online": True, "active_game": "idle",
            "active": [], "totals": {"daily": 0, "weekly": 0, "per_game": {}},
        }

    def async_add_listener(self, callback):
        return lambda: None


def restriction(*, options=None, data=None, device_id="pc1"):
    c = StubCoordinator(options=options, data=data, device_id=device_id)
    return GamingRestriction(c), c


def test_identity_and_initial_disabled_policy():
    entity, c = restriction()
    assert entity.name == "Gaming restriction"
    assert entity.unique_id == "pc1_gaming_restriction"
    assert entity.available
    assert entity.is_on is False
    assert entity.extra_state_attributes["reasons"] == []
    assert entity.extra_state_attributes["reason"] is None
    c.last_update_success = False
    assert not entity.available


@pytest.mark.parametrize("options,daily,weekly,expected", [
    ({"enabled": True, "daily": 60, "weekly": 300}, 3599, 0, []),
    ({"enabled": True, "daily": 60, "weekly": 300}, 3600, 0, ["daily"]),
    ({"enabled": True, "daily": 60, "weekly": 300}, 3600, 18000, ["daily", "weekly"]),
    ({"enabled": True, "daily": -1, "weekly": 300}, 10000, 0, []),
    ({"enabled": True, "daily": -1, "weekly": 0}, 10000, 0, ["weekly"]),
    ({"enabled": True, "daily": 0, "weekly": 300}, 0, 0, ["daily"]),
    ({"enabled": False, "daily": 0, "weekly": 0}, 5000, 5000, []),
    ({"enabled": True, "unlimited": True, "daily": 0, "weekly": 0}, 5000, 5000, []),
])
def test_budget_and_safe_override(options, daily, weekly, expected):
    entity, c = restriction(options=options)
    c.data["totals"].update(daily=daily, weekly=weekly)
    with patch("custom_components.smarthouse_gaming.binary_sensor.dt_util.now",
               return_value=at(18)):
        assert entity.available
        assert entity.is_on is bool(expected)
        assert entity.extra_state_attributes["reasons"] == expected
        assert entity.extra_state_attributes["reason"] == (expected[0] if expected else None)


def test_bonus_is_day_scoped_and_weekly_cap_stays_independent():
    entity, c = restriction(options={
        "enabled": True, "daily": 60, "weekly": 300, "weekend_bonus": 60,
        "bonus_date": "2026-11-21", "bonus_minutes": 30,
    })
    c.data["totals"].update(daily=120 * 60, weekly=120 * 60)
    with patch("custom_components.smarthouse_gaming.binary_sensor.dt_util.now",
               return_value=at(21)):
        assert entity.available and not entity.is_on  # 60 + 60 + 30
    with patch("custom_components.smarthouse_gaming.binary_sensor.dt_util.now",
               return_value=at(22)):
        assert entity.is_on  # 60 + 60, one-off bonus expired
    with patch("custom_components.smarthouse_gaming.binary_sensor.dt_util.now",
               return_value=at(23)):
        assert entity.is_on  # weekday budget is only 60
    c.options["weekly"] = 120
    with patch("custom_components.smarthouse_gaming.binary_sensor.dt_util.now",
               return_value=at(21)):
        assert entity.extra_state_attributes["reasons"] == ["weekly"]


def test_schedule_restriction_without_active_game_and_per_game_only_when_active():
    entity, c = restriction(options={
        "enabled": True, "daily": 100, "weekly": 4200,
        "schedule_enabled": True, "schedule_start": "16:00",
        "schedule_end": "20:00", "per_game": {"Roblox": 10},
    })
    c.data["totals"]["per_game"] = {"Roblox": 600}
    with patch("custom_components.smarthouse_gaming.binary_sensor.dt_util.now",
               return_value=at(18)):
        assert entity.is_on
        assert entity.extra_state_attributes["reasons"] == ["schedule"]
    with patch("custom_components.smarthouse_gaming.binary_sensor.dt_util.now",
               return_value=at(18, 18)):
        assert not entity.is_on
        c.data["active"] = ["Roblox"]
        c.data["active_game"] = "Roblox"
        assert entity.is_on
        assert entity.extra_state_attributes["reasons"] == ["game:Roblox"]
        c.data["active"] = []
        c.data["active_game"] = "idle"
        assert not entity.is_on


def test_unknown_measurements_are_never_reported_as_off_or_on():
    entity, c = restriction(options={"enabled": True, "daily": 0})
    assert entity.available and entity.is_on
    c.data["ready"] = False
    assert not entity.available
    assert entity.is_on is None
    assert entity.extra_state_attributes["reasons"] is None
    c.data["recorded_totals"] = {"daily": 1800, "weekly": 1800}
    assert not entity.available  # old history cannot prove current policy
    c.data["ready"] = True
    c.data["online"] = False
    assert not entity.available  # offline Recorder data alone is not a live verdict
    assert entity.is_on is None
    c.data["online"] = True
    for bad in (
        {}, {"daily": 0}, {"daily": None, "weekly": 0, "per_game": {}},
        {"daily": float("nan"), "weekly": 0, "per_game": {}},
        {"daily": -1, "weekly": 0, "per_game": {}},
        {"daily": 0, "weekly": 0, "per_game": None},
    ):
        c.data["totals"] = bad
        assert not entity.available
        assert entity.is_on is None
    c.data["totals"] = {"daily": 0, "weekly": 0, "per_game": {}}
    c.data.pop("active")
    assert not entity.available


def test_device_isolation_and_game_evidence():
    a, ca = restriction(options={"enabled": True, "daily": 0})
    b, cb = restriction(device_id="pc2", options={"enabled": True, "daily": 60})
    assert a.unique_id != b.unique_id
    assert a.is_on and not b.is_on
    ca.data["active"] = ["Roblox"]
    ca.options["per_game"] = {"Roblox": 10}
    # No matching per-game totals: do not assume that a game has used zero time.
    assert not a.available
    cb.data["totals"]["daily"] = 3600
    assert b.is_on


@pytest.mark.asyncio
async def test_rules_enabled_has_explicit_parent_opt_in_and_never_publishes():
    """Switch defaults off and changes only HA-local options, even if PC is offline."""
    entity, c = restriction(options={"daily": 60, "actions": ["terminate_game"]})
    c.data["ready"] = False
    toggle = GamingRulesSwitch(c)
    assert toggle.unique_id == "pc1_gaming_rules_enabled"
    assert toggle.name == "Gaming rules enabled"
    assert toggle.available
    assert toggle.is_on is False
    changes = []

    def save(entry, *, options):
        changes.append(dict(options))
        entry.options = dict(options)
        c.options = DEFAULTS | entry.options

    toggle.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=save))
    with patch.object(toggle, "async_write_ha_state"):
        await toggle.async_turn_on()
        assert toggle.is_on is True
        assert c.entry.options["actions"] == ["terminate_game"]
        assert c.entry.options["daily"] == 60
        await toggle.async_turn_on()  # no duplicate option write
        await toggle.async_turn_off()
        assert toggle.is_on is False
        assert len(changes) == 2
    assert entity.is_on is None  # offline stays unknown regardless of switch
