"""Issue #165: stable, durable parent bonus grants and safe per-grant revocation."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from custom_components.hal_gaming_control.parent_bonus import (
    add_parent_grant, revoke_parent_grant, parent_bonus_total, parent_grants_today,
)
from custom_components.hal_gaming_control.rule_engine import effective_budget_limit

TZ = ZoneInfo("Europe/Zagreb")


def now(day=22, hour=14, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def test_three_grants_middle_cancel_is_idempotent_and_does_not_change_usage():
    opts = {"enabled": True, "daily": 180, "weekly": 300}
    for minute in (1, 2, 3):
        opts = add_parent_grant(opts, "pc1", now(minute=minute), 30)
    grants = parent_grants_today(opts, now())
    ids = [x["id"] for x in grants]
    assert len(ids) == len(set(ids)) == 3
    assert opts["bonus_minutes"] == parent_bonus_total(opts, now()) == 90
    assert effective_budget_limit(opts, now(), "daily") == 270
    assert effective_budget_limit(opts, now(), "weekly") == 300
    opts = revoke_parent_grant(opts, "pc1", ids[1], now(minute=5))
    assert opts["bonus_minutes"] == parent_bonus_total(opts, now()) == 60
    assert effective_budget_limit(opts, now(), "daily") == 240
    assert len(parent_grants_today(opts, now())) == 2
    cancelled = [e for e in opts["parent_bonus_journal"]["events"]
                 if e["id"] == ids[1]]
    assert cancelled[0]["status"] == "cancelled"
    assert cancelled[0]["cancelled_at_utc"] is not None
    with pytest.raises(ValueError, match="cancelled"):
        revoke_parent_grant(opts, "pc1", ids[1], now(minute=6))
    assert opts["bonus_minutes"] == 60
    assert "daily_used" not in opts


def test_legacy_bonus_is_unattributed_not_fake_historical_events():
    opts = {"daily": 180, "bonus_date": "2026-11-22", "bonus_minutes": 45}
    upgraded = add_parent_grant(opts, "pc1", now(), 30)
    assert upgraded["parent_bonus_journal"]["legacy"] == {
        "date": "2026-11-22", "minutes": 45,
    }
    assert len(upgraded["parent_bonus_journal"]["events"]) == 1
    assert parent_bonus_total(upgraded, now()) == 75
    assert upgraded["bonus_minutes"] == 75
    assert opts == {"daily": 180, "bonus_date": "2026-11-22", "bonus_minutes": 45}
    with pytest.raises(ValueError, match="Unknown"):
        revoke_parent_grant(upgraded, "pc1", "legacy", now())
    assert parent_bonus_total(upgraded, now(23)) == 0


def test_cross_device_and_expired_grants_must_not_revoke():
    opts = add_parent_grant({"daily": 120}, "pc1", now(), 30)
    grant_id = parent_grants_today(opts, now())[0]["id"]
    for dev, when, message in [("pc2", now(), "device"), ("pc1", now(23), "expired")]:
        with pytest.raises(ValueError, match=message):
            revoke_parent_grant(opts, dev, grant_id, when)
    assert parent_bonus_total(opts, now()) == 30


def test_persistent_json_and_local_day_rollover_preserve_audit():
    first = add_parent_grant({"daily": 100}, "pc1", now(), 30)
    second = add_parent_grant(json.loads(json.dumps(first)), "pc1", now(23), 30)
    assert second["bonus_date"] == "2026-11-23"
    assert second["bonus_minutes"] == parent_bonus_total(second, now(23)) == 30
    assert parent_bonus_total(second, now()) == 30
    assert len(second["parent_bonus_journal"]["events"]) == 2
    assert [e["local_date"] for e in second["parent_bonus_journal"]["events"]] == [
        "2026-11-22", "2026-11-23",
    ]


def test_unknown_or_broken_ledger_refuses_to_overwrite_audit():
    corrupt = {"daily": 120, "parent_bonus_journal": {"version": 99, "events": []}}
    with pytest.raises(ValueError, match="journal"):
        add_parent_grant(corrupt, "pc1", now(), 30)
    with pytest.raises(ValueError, match="journal"):
        parent_bonus_total(corrupt, now())


def test_bonus_event_time_is_utc_even_during_dst_overlap():
    # 02:30 occurs twice in Europe/Zagreb on fallback Sunday.
    first = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=0)
    second = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=1)
    opts = add_parent_grant({}, "pc1", first, 30)
    opts = add_parent_grant(opts, "pc1", second, 30)
    timestamps = [e["created_at_utc"]
                  for e in opts["parent_bonus_journal"]["events"]]
    assert timestamps[0] != timestamps[1]
    assert parent_bonus_total(opts, second) == 60


@pytest.mark.asyncio
async def test_add_30_button_produces_visible_distinct_entries_without_windows_commands():
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from custom_components.hal_gaming_control.button import AddDailyBudget
    from custom_components.hal_gaming_control.const import DEFAULTS
    from custom_components.hal_gaming_control.rule_engine import budget_overview

    entry = SimpleNamespace(data={"device_id": "pc1", "name": "Test PC"},
                            options={"enabled": True, "daily": 180, "weekly": 300})
    c = Mock()
    c.device_id = "pc1"
    c.entry = entry
    c.last_update_success = True
    c.options = DEFAULTS | entry.options

    def save(_entry, *, options):
        entry.options = options
        c.options = DEFAULTS | options

    add = AddDailyBudget(c)
    add.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=save))
    with patch("custom_components.hal_gaming_control.button.dt_util.now",
               return_value=now()):
        await add.async_press()
        await add.async_press()
    assert len(parent_grants_today(entry.options, now())) == 2
    receipt = budget_overview(c.options, {"daily": 0, "weekly": 0},
                              now(), ready=True)
    assert receipt["parent_bonus_minutes"] == 60
    assert len(receipt["parent_bonus_grants_today"]) == 2
    assert receipt["parent_bonus_recent_action"]["action"] == "added"
    assert receipt["parent_bonus_recent_action"]["minutes"] == 30
    assert receipt["parent_bonus_legacy_minutes"] == 0
    assert receipt["weekly_limit_minutes"] == 300
    assert "actions" not in entry.options



def test_budget_overview_recorder_attrs_bounded_and_cancel_receipt_is_latest():
    """30 grants should not persist two huge copies in Recorder attrs.

    A cancellation of an older grant is the last *action*, even if a newer
    grant still exists. Full journal and native select keep all active IDs.
    """
    from custom_components.hal_gaming_control.rule_engine import budget_overview
    opts = {"enabled": True, "daily": 120, "weekly": 300}
    for minute in range(1, 31):
        opts = add_parent_grant(opts, "pc1", now(minute=minute), 30)

    original = parent_grants_today(opts, now())
    assert len(original) == 30
    grant_id = original[15]["id"]
    opts = revoke_parent_grant(opts, "pc1", grant_id, now(minute=45))
    overview = budget_overview(
        opts, {"daily": 0, "weekly": 0}, now(minute=46), ready=True)
    assert len(overview["parent_bonus_grants_today"]) == 12
    assert len(overview["parent_bonus_activity_today"]) == 12
    assert overview["parent_bonus_recent_action"] == {
        "action": "cancelled",
        "minutes": 30,
        "at_utc": next(
            e["cancelled_at_utc"]
            for e in opts["parent_bonus_journal"]["events"]
            if e["id"] == grant_id
        ),
        "grant_id": grant_id,
    }
    assert len(opts["parent_bonus_journal"]["events"]) == 30
    assert len(parent_grants_today(opts, now())) == 29
    assert overview["parent_bonus_minutes"] == 29 * 30
    assert "daily_used" not in opts
