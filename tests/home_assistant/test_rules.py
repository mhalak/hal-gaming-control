from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from custom_components.hal_gaming_control.rule_engine import calculate, violations, windows, remaining_budget_percent, effective_budget_limit, daily_bonus_minutes
from custom_components.hal_gaming_control.const import DEFAULTS
from custom_components.hal_gaming_control.protocol import parse_discovery
from custom_components.hal_gaming_control.action_registry import available_actions, selected_actions
import json

TZ = ZoneInfo("Europe/Zagreb")
def dt(day, hour=0, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)
def point(day, hour, minute, state):
    return (dt(day, hour, minute).timestamp(), state)

def test_weekend_and_concurrent_games():
    records = [point(16, 10, 0, "Roblox"), point(16, 11, 0, "idle"),
               point(21, 10, 0, "Minecraft | Roblox"), point(21, 10, 30, "Roblox"),
               point(21, 11, 0, "unavailable"), point(21, 12, 0, "idle")]
    totals = calculate(records, dt(21, 13), ["Minecraft", "Roblox"])
    assert totals["daily"] == 3600
    assert totals["weekly"] == 7200
    assert totals["weekend_total"] == 3600
    assert totals["per_game"] == {"Minecraft": 1800, "Roblox": 3600}

def test_limits_intersect():
    options = DEFAULTS | {"enabled":True, "daily":0, "weekly":60, "weekend_bonus":30,
                          "weekend_total":120, "per_game":{"Roblox":15}}
    totals = {"daily":1800,"weekly":3600,"weekend_total":1800,"per_game":{"Roblox":900}}
    assert violations(options,totals,dt(21,12),["Roblox"]) == ["daily","weekly","game:Roblox"]
    assert violations(options | {"unlimited":True},totals,dt(21,12),["Roblox"]) == []

def test_schedule_and_disabled_default():
    totals = {"daily":0,"weekly":0,"weekend_total":0,"per_game":{}}
    options = DEFAULTS | {"enabled":True,"schedule_enabled":True,"schedule_start":"22:00","schedule_end":"02:00"}
    assert not violations(options,totals,dt(21,23),[])
    assert violations(options,totals,dt(21,12),[]) == ["schedule"]
    assert not violations(options | {"enabled":False},totals,dt(21,12),[])
    assert violations(DEFAULTS | {"enabled":True,"daily":0},totals,dt(21,12),[]) == ["daily"]

def test_monday_boundary_and_unknown():
    records = [point(15,23,30,"Roblox"), point(16,0,30,"unavailable"), point(16,1,30,"Roblox")]
    totals = calculate(records,dt(16,2),["Roblox"])
    assert totals["weekly"] == totals["daily"] == 3600
    assert totals["weekend_total"] == 0

def test_discovery_and_actions():
    data = {"device_id":"pc1","name":"PC 1","protocol_version":1,"games":["Roblox"],"actions":["lock_pc","evil","terminate_game"]}
    parsed = parse_discovery("SmartHouse/Gaming/pc1/discovery",json.dumps(data))
    assert parsed["actions"] == ["terminate_game","lock_pc"]
    assert available_actions(parsed["actions"],["lock_pc"]) == ["terminate_game"]
    assert selected_actions(parsed["actions"],["lock_pc","lock_pc","evil","terminate_game"]) == ["lock_pc","terminate_game"]
    with pytest.raises(ValueError):
        parse_discovery("SmartHouse/Gaming/pc2/discovery",json.dumps(data))
    with pytest.raises(ValueError):
        parse_discovery("SmartHouse/Gaming/pc1/discovery",json.dumps(data | {"protocol_version":2}))


@pytest.mark.parametrize("period,day,used,expected", [
    ("daily", 16, 0, 100.0),
    ("daily", 16, 900, 75.0),
    ("daily", 16, 3600, 0.0),
    ("daily", 16, 7200, 0.0),
    ("daily", 21, 3600, 50.0),
    ("weekly", 21, 3600, 80.0),
    ("weekly", 23, 0, 100.0),
])
def test_budget_percent(period, day, used, expected):
    opts = {"enabled": True, "daily": 60, "weekly": 300, "weekend_bonus": 60}
    assert remaining_budget_percent(opts, {period: used}, dt(day), period) == expected


@pytest.mark.parametrize("overrides,totals,expected", [
    ({"daily": -1}, {"daily": 0}, None),
    ({"daily": 0}, {"daily": 0}, 0.0),
    ({"enabled": False}, {"daily": 900}, None),
    ({"unlimited": True}, {"daily": 900}, None),
    ({}, {}, None),
    ({"weekend_bonus": 0}, {"daily": 900}, 75.0),
])
def test_budget_no_limit_and_weekend_zero_bonus(overrides, totals, expected):
    opts = {"enabled": True, "daily": 60} | overrides
    assert remaining_budget_percent(opts, totals, dt(21), "daily") == expected


def test_budget_is_independent_of_other_limits_and_schedule():
    opts = {"enabled": True, "daily": 60, "weekly": 0, "weekend_total": 0,
            "schedule_enabled": True, "schedule_start": "16:00", "schedule_end": "20:00"}
    totals = {"daily": 900, "weekly": 900, "weekend_total": 900}
    assert remaining_budget_percent(opts, totals, dt(21), "daily") == 75.0
    assert remaining_budget_percent(opts, totals, dt(21), "weekly") == 0.0


@pytest.mark.parametrize("day,expected", [(20, 50.0), (21, 75.0), (22, 75.0), (23, 50.0)])
def test_budget_weekday_weekend_boundaries(day, expected):
    options = {"enabled": True, "daily": 60, "weekend_bonus": 60}
    assert remaining_budget_percent(options, {"daily": 1800}, dt(day), "daily") == expected


def test_legacy_weekend_total_is_ignored_and_override_bypasses_all_rules():
    options = DEFAULTS | {"enabled": True, "daily": 60, "weekly": 300,
                          "weekend_bonus": 60, "weekend_total": 0}
    totals = {"daily": 1800, "weekly": 3600, "per_game": {"Roblox": 1800}}
    assert violations(options, totals, dt(21, 12), ["Roblox"]) == []
    blocked = options | {"daily": 0, "weekly": 0, "weekend_bonus": 0,
                         "schedule_enabled": True, "per_game": {"Roblox": 0}}
    assert violations(blocked, totals, dt(21, 12), ["Roblox"]) == [
        "daily", "weekly", "schedule", "game:Roblox"]
    assert violations(blocked | {"unlimited": True}, totals, dt(21, 12), ["Roblox"]) == []
    assert violations(blocked, totals, dt(21, 12), ["Roblox"])


def test_bonus_stacks_only_today_and_affects_both_enforcement_and_display():
    opts = DEFAULTS | {"enabled": True, "daily":60, "weekend_bonus":60, "weekly":300,
                       "bonus_date":"2026-11-21", "bonus_minutes":60}
    totals = {"daily":7200, "weekly":7200, "per_game":{}}
    assert effective_budget_limit(opts, dt(21), "daily") == 180
    assert remaining_budget_percent(opts, totals, dt(21), "daily") == 33.3
    assert not violations(opts, totals, dt(21), [])
    assert "daily" in violations(opts, totals, dt(22), [])
    assert effective_budget_limit(opts, dt(22), "daily") == 120
    assert daily_bonus_minutes(opts, dt(22)) == 0
    assert effective_budget_limit(opts, dt(21), "weekly") == 300
    assert remaining_budget_percent(opts, totals, dt(21), "weekly") == 60.0
    assert effective_budget_limit(opts | {"daily":-1,"weekend_bonus":0}, dt(21), "daily") == -1


def test_bonus_can_extend_zero_daily_limit_but_not_weekly_or_schedule():
    opts = DEFAULTS | {"enabled":True,"daily":0,"weekly":0,"bonus_date":"2026-11-18",
                       "bonus_minutes":30,"schedule_enabled":True}
    totals = {"daily":0,"weekly":0,"per_game":{}}
    assert remaining_budget_percent(opts, totals, dt(18), "daily") == 100
    assert violations(opts, totals, dt(18), []) == ["weekly","schedule"]

# Additive weekend bonus contract, active on both weekend days.
@pytest.mark.parametrize("day,expected", [(20,60),(21,100),(22,100),(23,60)])
def test_opt_in_weekend_bonus_adds_to_weekday_base(day, expected):
    from custom_components.hal_gaming_control.rule_engine import effective_budget_limit
    opts = DEFAULTS | {"daily": 60, "weekend_bonus": 40}
    assert effective_budget_limit(opts, dt(day), "daily") == expected


def test_opt_in_bonus_preserves_unlimited_zero_bonus_and_weekly_independence():
    options = DEFAULTS | {"enabled": True, "daily": 0, "weekly": 90,
                          "weekend_bonus": 30, "bonus_date": "2026-11-21",
                          "bonus_minutes": 20}
    assert effective_budget_limit(options, dt(21), "daily") == 50
    assert effective_budget_limit(options, dt(20), "daily") == 0
    assert effective_budget_limit(options, dt(22), "daily") == 30
    assert effective_budget_limit(options, dt(21), "weekly") == 90
    assert effective_budget_limit(options | {"daily": -1}, dt(21), "daily") == -1
    options["daily"] = 0
    options["weekend_bonus"] = 0
    assert effective_budget_limit(options, dt(21), "daily") == 20


@pytest.mark.parametrize("value", [-1, 5, 601, True, None, "20", 3.5])
def test_opt_in_weekend_bonus_rejects_malformed_config(value):
    options = DEFAULTS | {"daily": 60, "weekend_bonus": value}
    with pytest.raises(ValueError, match="weekend bonus"):
        effective_budget_limit(options, dt(21), "daily")


def test_retired_legacy_weekend_override_is_ignored():
    options = DEFAULTS | {"daily": 60, "weekly": 300, "weekend_daily": 120}
    assert effective_budget_limit(options, dt(20), "daily") == 60
    assert effective_budget_limit(options, dt(21), "daily") == 60
    assert options["weekend_bonus"] == 0
