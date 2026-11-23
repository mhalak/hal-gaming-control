"""Budget receipt dropdown: ordered sources, locked rows, safe whole-grant Undo."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.hal_gaming_control.budget_select import budget_select_rows
from custom_components.hal_gaming_control.parent_bonus import (
    add_parent_grant, parent_grants_today, parent_bonus_total,
)
from custom_components.hal_gaming_control.select import ParentBonusGrantSelect

TZ = ZoneInfo("Europe/Zagreb")


def at(hour, minute=0):
    return datetime(2026, 11, 23, hour, minute, tzinfo=TZ)


def sample_receipt(*, used=0, ready=True):
    """180 base +30 at 11:40 +10 Screen off 12:50 +30 at 14:00 = 250."""
    opts = {"daily": 180, "weekly": 600, "enabled": True}
    opts = add_parent_grant(opts, "pc1", at(11, 40), 30)
    opts["screen_idle_bonus_journal"] = {
        "version": 1, "device_id": "pc1", "events": [{
            "id": "b" * 32 + ":12", "date": "2026-11-23",
            "minutes": 10, "off_at_utc": at(12, 50).timestamp(),
        }],
    }
    opts = add_parent_grant(opts, "pc1", at(14), 30)
    data = {
        "ready": ready, "totals": {"daily": used, "weekly": used},
        "coverage_incomplete": False,
    }
    return opts, data


def rows(opts, data, when=None):
    with patch("custom_components.hal_gaming_control.budget_select.dt_util.as_local",
               side_effect=lambda d: d.astimezone(TZ)):
        return budget_select_rows(opts, "pc1", data, when or at(15))


def test_two_versions_same_source_receipt_and_locked_rows():
    opts, data = sample_receipt()
    entries = rows(opts, data)
    labels = [label for label, _ in entries]
    assert labels == [
        "🔒 +180min Daily budget",
        "+30min Parent bonus (11:40)",
        "🔒 +10min Screen off bonus (12:50)",
        "+30min Parent bonus (14:00)",
        "🔒 250min TOTAL",
    ]
    ids = [grant_id for _, grant_id in entries]
    assert ids[0] is None and ids[2] is None and ids[4] is None
    assert ids[1] and ids[3] and ids[1] != ids[3]
    assert parent_bonus_total(opts, at(15)) == 60


@pytest.mark.parametrize("used,locked,can_undo", [
    (180 * 60, 0, 2),       # Base exactly exhausted; both bonuses untouched.
    (180 * 60 + 1, 1, 1),   # Oldest Parent touched by one second: locked.
    (210 * 60, 1, 1),      # Screen-off allowance untouched? Its row is always locked.
    (220 * 60, 1, 1),      # Last parent is still untouched.
    (220 * 60 + 1, 2, 0),  # Last Parent now touched by one second.
    (250 * 60, 2, 0),
])
def test_spending_any_fraction_locks_that_parent_grant(used, locked, can_undo):
    opts, data = sample_receipt(used=used)
    entries = rows(opts, data)
    parent_rows = [(label, grant_id) for label, grant_id in entries
                   if "Parent bonus" in label]
    assert len(parent_rows) == 2
    assert sum(label.startswith("🔒") for label, _ in parent_rows) == locked
    assert sum(grant_id is not None for _, grant_id in parent_rows) == can_undo


@pytest.mark.parametrize("overrides", [
    {"ready": False},
])
def test_missing_live_usage_always_locks_all_parent_bonuses(overrides):
    opts, data = sample_receipt(used=0, **overrides)
    entries = rows(opts, data)
    assert all(grant_id is None for _, grant_id in entries)


@pytest.mark.parametrize("policy", [
    {"enabled": False}, {"unlimited": True}, {"daily": -1},
])
def test_unlimited_and_disabled_policy_do_not_offer_revocation(policy):
    opts, data = sample_receipt()
    opts.update(policy)
    entries = rows(opts, data)
    assert all(grant_id is None for _, grant_id in entries)


@pytest.mark.asyncio
async def test_locked_rows_cannot_be_selected_even_by_direct_service_call():
    opts, data = sample_receipt(used=180 * 60 + 1)
    entry = SimpleNamespace(data={"device_id": "pc1", "name": "PC"}, options=opts)
    coordinator = Mock(device_id="pc1", entry=entry, data=data,
                       last_update_success=True)
    entity = ParentBonusGrantSelect(coordinator)
    entity.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=Mock()))
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at(15)), patch.object(entity, "async_write_ha_state"):
        dropdown = entity.options
        assert "🔒 +180min Daily budget" in dropdown
        assert "🔒 +30min Parent bonus (11:40)" in dropdown
        assert "🔒 250min TOTAL" in dropdown
        assert "+30min Parent bonus (14:00)" in dropdown
        for label in dropdown:
            if label.startswith("🔒"):
                with pytest.raises(HomeAssistantError, match="locked"):
                    await entity.async_select_option(label)
        await entity.async_select_option("+30min Parent bonus (14:00)")
        assert entity.current_option == "+30min Parent bonus (14:00)"


@pytest.mark.asyncio
async def test_minutes_spent_after_prepare_block_confirm_without_mutation():
    opts, data = sample_receipt(used=200 * 60)
    entry = SimpleNamespace(data={"device_id": "pc1", "name": "PC"}, options=opts)
    coordinator = Mock(device_id="pc1", entry=entry, data=data,
                       last_update_success=True)
    updates = Mock()
    entity = ParentBonusGrantSelect(coordinator)
    entity.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=updates))
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at(15)), patch(
                   "custom_components.hal_gaming_control.select.monotonic",
                   return_value=25.0), patch.object(entity, "async_write_ha_state"):
        await entity.async_select_option("+30min Parent bonus (14:00)")
        entity.prepare("parent-A")
        data["totals"]["daily"] = 220 * 60 + 1
        with pytest.raises(HomeAssistantError, match="selection changed"):
            entity.confirm("parent-A")
    updates.assert_not_called()
    assert parent_bonus_total(entry.options, at(15)) == 60


@pytest.mark.asyncio
async def test_exactly_zero_after_revoke_is_accepted():
    opts, data = sample_receipt(used=180 * 60)
    # Remove screen bonus and second parent, leaving base + first parent.
    opts["screen_idle_bonus_journal"]["events"].clear()
    latest = parent_grants_today(opts, at(15))[0]
    opts["parent_bonus_journal"]["events"] = [
        item for item in opts["parent_bonus_journal"]["events"]
        if item["id"] != latest["id"]]
    entries = rows(opts, data)
    parent_row = next((label, gid) for label, gid in entries
                      if gid is not None and "Parent bonus" in label)
    assert parent_row[0] == "+30min Parent bonus (11:40)"
    assert data["totals"]["daily"] == (
        180 * 60) == (210 - 30) * 60
