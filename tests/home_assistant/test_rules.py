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


# Smart budget contract: signed seconds preserve overrun debt when granting.
@pytest.mark.parametrize("remaining,expected,adjustments", [
    ((120, 300, 360), 120, (30, 0, 0)),
    ((120, 300, 120), 120, (30, 0, 30)),
    ((0, 20, 15), 0, (30, 10, 15)),
    ((180, 60, 360), 60, (0, 30, 0)),
    ((60, 120, 15), 15, (0, 0, 30)),
    ((0, 120, 360), 0, (30, 0, 0)),
    ((40, 60, 360), 40, (30, 10, 0)),
    ((-5, 120, 360), 0, (35, 0, 0)),
])
def test_smart_budget_plan(remaining, expected, adjustments):
    from custom_components.hal_gaming_control.smart_budget import select_budget, plan_bonus
    balances = dict(zip(("daily", "weekly", "schedule"), (m * 60 for m in remaining)))
    selected = select_budget(balances)
    assert selected.remaining_seconds == expected * 60
    plan = plan_bonus(selected, 1800)
    assert plan.target_seconds == (expected + 30) * 60
    assert tuple(plan.extensions.get(key, 0) for key in balances) == tuple(m * 60 for m in adjustments)
    after = select_budget({key: value + plan.extensions.get(key, 0)
                           for key, value in balances.items()})
    assert after.remaining_seconds == plan.target_seconds


def test_smart_budget_disabled_unknown_ties_and_zero():
    from custom_components.hal_gaming_control.smart_budget import select_budget, plan_bonus
    assert select_budget({}).status == "unlimited"
    assert select_budget({}, enabled=False).status == "disabled"
    assert select_budget({"daily": 5}, unlimited=True).status == "unlimited"
    unknown = select_budget({"daily": 0, "weekly": None})
    assert unknown.status == "unknown"
    assert unknown.remaining_seconds is None
    with pytest.raises(ValueError):
        plan_bonus(unknown, 60)
    tied = select_budget({"weekly": 0, "daily": -10, "schedule": 10})
    assert tied.remaining_seconds == 0
    assert tied.limiting_sources == ("daily", "weekly")
    assert select_budget({"schedule": 0}).limiting_sources == ("schedule",)
    assert plan_bonus(select_budget({"schedule": 0}), 1800).extensions == {"schedule": 1800}


@pytest.mark.parametrize("value", [True, "10", float("nan"), float("inf")])
def test_smart_budget_invalid_balance(value):
    from custom_components.hal_gaming_control.smart_budget import select_budget
    assert select_budget({"daily": value}).status == "unknown"


@pytest.mark.parametrize("amount", [0, -1, True, float("inf"), 1.5])
def test_smart_budget_invalid_grant(amount):
    from custom_components.hal_gaming_control.smart_budget import select_budget, plan_bonus
    with pytest.raises(ValueError):
        plan_bonus(select_budget({"daily": 10}), amount)


def test_smart_budget_fractional_usage_and_input_isolation():
    from custom_components.hal_gaming_control.smart_budget import select_budget, plan_bonus
    raw = {"daily": 0.25, "weekly": 100}
    selected = select_budget(raw)
    raw["daily"] = 100
    assert selected.remaining_seconds == 0.25
    plan = plan_bonus(selected, 60)
    assert plan.extensions == {"daily": 60}
    assert plan.target_seconds == 60.25
    for snapshot in (select_budget({}), select_budget({}, enabled=False)):
        with pytest.raises(ValueError):
            plan_bonus(snapshot, 60)


# Smart schedule: absolute elapsed seconds, shared recurring-window semantics.
def smart_schedule_options(**overrides):
    return DEFAULTS | {"enabled": True, "schedule_enabled": True,
                       "schedule_start": "16:00", "schedule_end": "22:00"} | overrides


@pytest.mark.parametrize("hour,minute,expected", [(21, 45, 900), (22, 0, 0), (23, 0, 0), (15, 0, 0)])
def test_smart_schedule_regular(hour, minute, expected):
    from custom_components.hal_gaming_control.smart_schedule import schedule_snapshot
    state = schedule_snapshot(smart_schedule_options(), dt(20, hour, minute))
    assert state.remaining_seconds == expected


def test_smart_schedule_extension_is_absolute_and_reopens():
    from datetime import timedelta
    from custom_components.hal_gaming_control.smart_schedule import schedule_snapshot, extend_schedule
    opts = smart_schedule_options()
    now = dt(20, 21, 45)
    extension = extend_schedule(schedule_snapshot(opts, now), now, 1800)
    assert extension.end == dt(20, 22, 30)
    assert schedule_snapshot(opts, dt(20, 22, 10), extension).remaining_seconds == 1200
    assert schedule_snapshot(opts, dt(20, 22, 30), extension).remaining_seconds == 0
    assert schedule_snapshot(opts, dt(20, 23, 30), extension).remaining_seconds == 0
    assert schedule_snapshot(opts, dt(21, 16), extension).remaining_seconds == 21600
    now = dt(20, 22, 20)
    reopened = extend_schedule(schedule_snapshot(opts, now), now, 1800)
    assert reopened.start == now and reopened.end == now + timedelta(minutes=30)
    assert schedule_snapshot(opts, now, reopened).remaining_seconds == 1800
    assert schedule_snapshot(opts, dt(20, 22, 19), reopened).remaining_seconds == 0


def test_smart_schedule_overnight_weekend_and_extension():
    from custom_components.hal_gaming_control.smart_schedule import schedule_snapshot, extend_schedule
    opts = smart_schedule_options(schedule_start="20:00", schedule_end="02:00",
                                  weekend_schedule_start="21:00", weekend_schedule_end="03:00")
    now = dt(21, 1, 45)
    state = schedule_snapshot(opts, now)
    assert state.remaining_seconds == 900 and state.deadline == dt(21, 2)
    grant = extend_schedule(state, now, 900)
    assert grant.end == dt(21, 2, 15)
    assert schedule_snapshot(opts, dt(21, 2, 10), grant).remaining_seconds == 300
    assert schedule_snapshot(opts, dt(21, 2, 15), grant).remaining_seconds == 0
    assert schedule_snapshot(opts, dt(22, 2), grant).remaining_seconds == 3600


def test_smart_schedule_all_day_contiguous_and_disabled():
    from custom_components.hal_gaming_control.smart_schedule import schedule_snapshot
    opts = smart_schedule_options(weekend_schedule_start="12:00", weekend_schedule_end="12:00")
    assert schedule_snapshot(opts, dt(21, 23)).deadline == dt(23)
    assert schedule_snapshot(opts, dt(22, 23)).remaining_seconds == 3600
    assert schedule_snapshot(opts | {"schedule_enabled": False}, dt(20, 12)).remaining_seconds is None
    assert schedule_snapshot(opts | {"unlimited": True}, dt(20, 12)).remaining_seconds is None
    assert schedule_snapshot(opts | {"enabled": False}, dt(20, 12)).remaining_seconds is None
    all_day = smart_schedule_options(schedule_start="00:00", schedule_end="00:00")
    assert schedule_snapshot(all_day, dt(20, 12)).remaining_seconds is None


def test_smart_schedule_dst_gap_and_fold_match_wall_clock_policy():
    from custom_components.hal_gaming_control.smart_schedule import schedule_snapshot
    opts = smart_schedule_options(schedule_start="20:00", schedule_end="02:30")
    spring = datetime(2026, 3, 29, 1, 45, tzinfo=TZ)
    assert schedule_snapshot(opts, spring).remaining_seconds == 900
    for fold in (0, 1):
        autumn = datetime(2026, 10, 25, 2, 15, tzinfo=TZ, fold=fold)
        assert schedule_snapshot(opts, autumn).remaining_seconds == 900
    autumn_closed = datetime(2026, 10, 25, 2, 45, tzinfo=TZ, fold=0)
    assert schedule_snapshot(opts, autumn_closed).remaining_seconds == 0


def test_smart_schedule_grants_merge_and_validation():
    from custom_components.hal_gaming_control.smart_schedule import schedule_snapshot, extend_schedule, ScheduleExtension
    opts = smart_schedule_options()
    now = dt(20, 21, 45)
    first = extend_schedule(schedule_snapshot(opts, now), now, 1800)
    later = dt(20, 22, 10)
    second = extend_schedule(schedule_snapshot(opts, later, first), later, 600)
    assert second.start == first.start and second.end == dt(20, 22, 40)
    assert schedule_snapshot(opts, later, second).remaining_seconds == 1800
    for invalid in (0, -1, True, float("nan")):
        with pytest.raises(ValueError):
            extend_schedule(schedule_snapshot(opts, now), now, invalid)
    with pytest.raises(ValueError):
        ScheduleExtension(dt(20, 22), dt(20, 21))
    with pytest.raises(ValueError):
        schedule_snapshot(opts, datetime(2026, 11, 20, 21))
    with pytest.raises(ValueError):
        extend_schedule(schedule_snapshot(opts | {"schedule_enabled": False}, now), now, 1800)


def test_smart_schedule_extension_crosses_midnight_and_joins_next_window():
    from custom_components.hal_gaming_control.smart_schedule import schedule_snapshot, extend_schedule
    opts = smart_schedule_options(schedule_start="16:00", schedule_end="23:45",
                                  weekend_schedule_start="00:15", weekend_schedule_end="02:00")
    now = dt(20, 23, 30)
    grant = extend_schedule(schedule_snapshot(opts, now), now, 2700)
    assert grant.end == dt(21, 0, 30)
    assert schedule_snapshot(opts, dt(21, 0, 10), grant).deadline == dt(21, 2)
    assert schedule_snapshot(opts, dt(21, 2), grant).remaining_seconds == 0


# Smart bonus adjustment records: JSON roundtrip and independent expiry.
from datetime import timedelta


def smart_record_at(day, hour=21, minute=45):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def test_smart_record_roundtrip_and_expiry():
    from custom_components.hal_gaming_control.smart_bonus_record import make_adjustments, active_adjustments
    now = smart_record_at(19)
    record = make_adjustments(now, {'daily': 1800, 'weekly': 600, 'schedule': 900},
                              schedule_anchor=smart_record_at(19, 22, 0))
    restored = json.loads(json.dumps(record))
    assert restored == record
    assert active_adjustments(restored, now).daily_seconds == 1800
    assert active_adjustments(restored, now).weekly_seconds == 600
    assert active_adjustments(restored, now).schedule_end == smart_record_at(19, 22, 15)
    assert active_adjustments(restored, smart_record_at(19, 22, 15)).schedule_end is None
    assert active_adjustments(restored, smart_record_at(20)).daily_seconds == 0
    assert active_adjustments(restored, smart_record_at(22)).weekly_seconds == 600
    assert active_adjustments(restored, smart_record_at(23)).weekly_seconds == 0
    assert active_adjustments(restored, smart_record_at(19, 21, 44)).weekly_seconds == 0


def test_smart_record_schedule_crosses_midnight():
    from custom_components.hal_gaming_control.smart_bonus_record import make_adjustments, active_adjustments
    now = smart_record_at(22, 23, 45)
    record = make_adjustments(now, {'daily': 60, 'weekly': 60, 'schedule': 1800},
                              schedule_anchor=now)
    later = active_adjustments(record, smart_record_at(23, 0, 5))
    assert later.daily_seconds == later.weekly_seconds == 0
    assert later.schedule_start == now
    assert later.schedule_end == smart_record_at(23, 0, 15)
    assert active_adjustments(record, smart_record_at(23, 0, 15)).schedule_end is None


def test_smart_record_preserves_fractional_seconds_and_utc():
    from custom_components.hal_gaming_control.smart_bonus_record import make_adjustments, active_adjustments
    now = smart_record_at(19)
    record = make_adjustments(now, {'daily': 10.25, 'weekly': 0.5})
    assert datetime.fromisoformat(record['granted_at_utc']).utcoffset() == timedelta(0)
    active = active_adjustments(record, now)
    assert (active.daily_seconds, active.weekly_seconds, active.schedule_end) == (10.25, 0.5, None)


@pytest.mark.parametrize('bad', [-1, True, float('nan'), float('inf'), '30'])
def test_smart_record_rejects_invalid_seconds(bad):
    from custom_components.hal_gaming_control.smart_bonus_record import make_adjustments
    with pytest.raises(ValueError):
        make_adjustments(smart_record_at(19), {'daily': bad})


def test_smart_record_rejects_corruption_and_bad_anchor():
    from custom_components.hal_gaming_control.smart_bonus_record import make_adjustments, active_adjustments
    now = smart_record_at(19)
    for adjustments, anchor in [({'schedule': 10}, None), ({'schedule': 10}, smart_record_at(19, 20)),
                                ({'weekly': 10}, now), ({'other': 10}, None)]:
        with pytest.raises(ValueError):
            make_adjustments(now, adjustments, schedule_anchor=anchor)
    with pytest.raises(ValueError):
        make_adjustments(now.replace(tzinfo=None), {'daily': 10})
    record = make_adjustments(now, {'schedule': 10}, schedule_anchor=now)
    for corrupt in [dict(record, version=2), dict(record, week='2026-11-19'),
                    dict(record, daily_seconds=True), dict(record, schedule_end_utc=record['schedule_start_utc']),
                    dict(record, schedule_start_utc=None), dict(record, granted_at_utc='invalid')]:
        with pytest.raises(ValueError):
            active_adjustments(corrupt, now)


def test_smart_journal_single_record_and_legacy_isolation():
    from custom_components.hal_gaming_control.parent_bonus import add_parent_grant, add_smart_parent_grant, parent_bonus_total, parent_smart_grants
    options = {'daily': 120, 'weekly': 300}
    legacy = add_parent_grant(options, 'pc1', smart_record_at(19), 15)
    candidate = add_smart_parent_grant(legacy, 'pc1', smart_record_at(19), 30,
                                      {'daily': 1800, 'weekly': 600, 'schedule': 900},
                                      schedule_anchor=smart_record_at(19, 22, 0))
    assert options == {'daily': 120, 'weekly': 300}
    assert len(legacy['parent_bonus_journal']['events']) == 1
    restored = json.loads(json.dumps(candidate))
    events = restored['parent_bonus_journal']['events']
    assert len(events) == 2 and events[-1]['minutes'] == 30
    assert parent_bonus_total(restored, smart_record_at(19)) == restored['bonus_minutes'] == 15
    active = parent_smart_grants(restored, 'pc1', smart_record_at(19))
    assert list(active) == [events[-1]['id']]
    assert active[events[-1]['id']].daily_seconds == 1800
    assert active[events[-1]['id']].schedule_end == smart_record_at(19, 22, 15)
    assert parent_smart_grants(restored, 'pc2', smart_record_at(19)) == {}
    assert parent_smart_grants(restored, 'pc1', smart_record_at(20))[events[-1]['id']].weekly_seconds == 600
    assert parent_smart_grants(restored, 'pc1', smart_record_at(23)) == {}


def test_smart_journal_cancelled_and_invalid_records():
    from custom_components.hal_gaming_control.parent_bonus import add_smart_parent_grant, revoke_parent_grant, parent_smart_grants, parent_grants_today
    candidate = add_smart_parent_grant({}, 'pc1', smart_record_at(19), 30, {'weekly': 1800})
    row = parent_grants_today(candidate, smart_record_at(19))[0]
    row['smart_adjustments']['weekly_seconds'] = -1
    grant_id = row['id']
    assert parent_smart_grants(candidate, 'pc1', smart_record_at(19))[grant_id].weekly_seconds == 1800
    revoked = revoke_parent_grant(candidate, 'pc1', grant_id, smart_record_at(19, 21, 46))
    assert parent_smart_grants(revoked, 'pc1', smart_record_at(20)) == {}
    bad = json.loads(json.dumps(candidate))
    bad['parent_bonus_journal']['events'][0]['smart_adjustments']['day'] = '2026-11-20'
    with pytest.raises(ValueError, match='Smart bonus'):
        parent_smart_grants(bad, 'pc1', smart_record_at(19))


# Smart bonus replay: use historical intent, not stale adjustment amounts.
def replay_at(day, hour=None, minute=0):
    if hour is None:
        hour, minute = 21, 45
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def replay_options(**overrides):
    return {'enabled': True, 'schedule_enabled': True, 'schedule_start': '16:00', 'schedule_end': '22:00'} | overrides


def test_replay_recalculates_weekly_shortfall():
    from custom_components.hal_gaming_control.smart_bonus_replay import GrantIntent, replay_grants
    grants = [GrantIntent('a', replay_at(19, 16), 1800, {'daily': 0, 'weekly': 1200}),
              GrantIntent('b', replay_at(19, 16, 1), 1800, {'daily': 0, 'weekly': 1200})]
    full = replay_grants(grants)
    assert full['a'].plan.extensions == {'daily': 1800, 'weekly': 600}
    assert full['b'].plan.extensions == {'daily': 1800, 'weekly': 1800}
    remaining = replay_grants(grants, cancelled_ids={'a'})
    assert list(remaining) == ['b']
    assert remaining['b'].plan.extensions == {'daily': 1800, 'weekly': 600}
    assert grants[1].base_balances == {'daily': 0, 'weekly': 1200}


def test_replay_schedule_cancellation_rebases_and_reopens_at_original_grant():
    from custom_components.hal_gaming_control.smart_bonus_replay import GrantIntent, replay_grants
    grants = [GrantIntent('a', replay_at(19), 1800, {'daily': 3600}, replay_options()),
              GrantIntent('b', replay_at(19, 22, 10), 1800, {'daily': 3600}, replay_options())]
    full = replay_grants(grants)
    assert full['b'].schedule.start == replay_at(19, 22, 30)
    assert full['b'].schedule.end == replay_at(19, 23)
    remaining = replay_grants(grants, cancelled_ids={'a'})
    assert remaining['b'].schedule.start == replay_at(19, 22, 10)
    assert remaining['b'].schedule.end == replay_at(19, 22, 40)


def test_replay_daily_and_weekly_reset_and_usage_debt():
    from custom_components.hal_gaming_control.smart_bonus_replay import GrantIntent, replay_grants
    grants = [GrantIntent('a', replay_at(19), 1800, {'daily': 0, 'weekly': 0}),
              GrantIntent('b', replay_at(20), 1800, {'daily': 0, 'weekly': -600}),
              GrantIntent('c', replay_at(23), 1800, {'daily': 0, 'weekly': 0})]
    full = replay_grants(grants)
    assert full['b'].plan.extensions == {'daily': 1800, 'weekly': 600}
    assert full['c'].plan.extensions == {'daily': 1800, 'weekly': 1800}
    remaining = replay_grants(grants, cancelled_ids={'a'})
    assert remaining['b'].plan.extensions == {'daily': 1800, 'weekly': 2400}


def test_replay_disconnected_interval_never_opens_early():
    from custom_components.hal_gaming_control.smart_bonus_replay import project_schedule
    from custom_components.hal_gaming_control.smart_schedule import ScheduleExtension
    a = ScheduleExtension(replay_at(19, 22), replay_at(19, 22, 15))
    b = ScheduleExtension(replay_at(19, 22, 30), replay_at(19, 23))
    assert project_schedule(replay_options(), replay_at(19), [a, b]).deadline == replay_at(19, 22, 15)
    assert project_schedule(replay_options(), replay_at(19, 22, 20), [a, b]).remaining_seconds == 0
    assert project_schedule(replay_options(), replay_at(19, 22, 30), [a, b]).remaining_seconds == 1800


def test_replay_connected_intervals_and_regular_window():
    from custom_components.hal_gaming_control.smart_bonus_replay import project_schedule
    from custom_components.hal_gaming_control.smart_schedule import ScheduleExtension
    a = ScheduleExtension(replay_at(20, 22), replay_at(21, 0, 30))
    b = ScheduleExtension(replay_at(21, 2), replay_at(21, 2, 15))
    config = replay_options(weekend_schedule_start='00:15', weekend_schedule_end='02:00')
    assert project_schedule(config, replay_at(20), [b, a]).deadline == replay_at(21, 2, 15)
    assert project_schedule(config, replay_at(21, 2, 15), [a, b]).remaining_seconds == 0


def test_replay_rejects_bad_order_ids_and_unknown():
    from custom_components.hal_gaming_control.smart_bonus_replay import GrantIntent, replay_grants
    a = GrantIntent('a', replay_at(19), 1800, {'daily': 0})
    b = GrantIntent('b', replay_at(18), 1800, {'daily': 0})
    for grants, cancelled in [([a,a], set()), ([a,b], set()), ([a], {'missing'}),
                               ([GrantIntent('x', replay_at(19), 1800, {'weekly': None})], set())]:
        with pytest.raises(ValueError):
            replay_grants(grants, cancelled_ids=cancelled)


# Shared policy snapshot: exact-second balances and live restriction parity.
@pytest.mark.parametrize("daily,weekly,schedule,expected", [
    (120, 300, False, 120), (180, 60, False, 60),
    (60, 120, True, 15), (0, 20, True, 0),
])
def test_effective_snapshot_selects_real_limit(daily, weekly, schedule, expected):
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    opts = {"enabled": True, "daily": daily, "weekly": weekly,
            "schedule_enabled": schedule, "schedule_start": "16:00", "schedule_end": "22:00"}
    state = effective_snapshot(opts, {"daily": 0, "weekly": 0}, dt(19, 21, 45), "pc1", ready=True)
    assert state.selection.remaining_seconds == expected * 60
    assert state.base_balances["daily"] == daily * 60
    assert state.base_balances["weekly"] == weekly * 60


def test_effective_snapshot_journal_and_restriction_parity():
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant
    opts = DEFAULTS | {"enabled": True, "daily": 60, "weekly": 80,
                       "schedule_enabled": True, "schedule_start": "16:00", "schedule_end": "22:00"}
    now = dt(19, 21, 45)
    totals = {"daily": 3600, "weekly": 3600, "per_game": {}}
    state = effective_snapshot(opts, totals, now, "pc1", ready=True)
    assert state.selection.remaining_seconds == 0
    opts = prepare_grant(opts, "pc1", now, 30, state.base_balances, opts)
    state = effective_snapshot(opts, totals, now, "pc1", ready=True)
    assert state.selection.remaining_seconds == 1800
    assert state.schedule.deadline == dt(19, 22, 15)
    assert state.limits_seconds == {"daily": 5400, "weekly": 5400}
    assert not violations(opts, totals, now, [], device_id="pc1")
    assert violations(opts, totals, now, [], device_id="pc2") == ["daily"]
    assert violations(opts, totals, dt(19, 22, 15), [], device_id="pc1") == ["schedule"]
    assert effective_budget_limit(opts, now, "weekly", device_id="pc1") == 90
    assert remaining_budget_percent(opts, totals, now, "weekly", device_id="pc1") == 33.3


def test_effective_snapshot_invalid_offline_and_disabled():
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    opts = DEFAULTS | {"enabled": True, "daily": 60, "weekly": -1}
    now = dt(19, 21, 45)
    for totals, ready in [({}, True), ({"daily": True}, True), ({"daily": 0}, False)]:
        state = effective_snapshot(opts, totals, now, "pc1", ready=ready)
        assert state.selection.status == "unknown"
        assert state.selection.remaining_seconds is None
    assert effective_snapshot(opts | {"unlimited": True}, {}, now, "pc1", ready=False).selection.status == "unlimited"
    assert effective_snapshot(opts | {"enabled": False}, {}, now, "pc1", ready=False).selection.status == "disabled"
    assert effective_snapshot(opts | {"daily": -1}, {}, now, "pc1", ready=False).selection.status == "unlimited"


def test_effective_snapshot_legacy_and_fractional_adjustments():
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant
    opts = DEFAULTS | {"enabled": True, "daily": 60, "weekly": -1,
                       "bonus_date": "2026-11-19", "bonus_minutes": 10}
    now = dt(19, 21, 45)
    totals = {"daily": 4200.25}
    state = effective_snapshot(opts, totals, now, "pc1", ready=True)
    assert state.base_balances == {"daily": -0.25}
    opts = prepare_grant(opts, "pc1", now, 30, state.base_balances)
    state = effective_snapshot(opts, totals, now, "pc1", ready=True)
    assert state.selection.remaining_seconds == 1800
    assert state.limits_seconds["daily"] == 6000.25
    assert effective_snapshot(opts, {"daily": 0}, dt(20, 12), "pc1", ready=True).selection.remaining_seconds == 3600
