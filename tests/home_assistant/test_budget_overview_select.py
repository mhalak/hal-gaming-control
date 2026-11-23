"""Native Budget receipt with immediate, administrator-only Parent Undo."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.hal_gaming_control.budget_select import budget_select_rows
from custom_components.hal_gaming_control.parent_bonus import (
    add_parent_grant, parent_bonus_activity_today, parent_bonus_total,
)
from custom_components.hal_gaming_control.select import ParentBonusGrantSelect

TZ = ZoneInfo("Europe/Zagreb")


def at(hour=15, minute=0):
    return datetime(2026, 11, 23, hour, minute, tzinfo=TZ)


def sample_receipt(*, used=0, ready=True, screen=True):
    """180 base +30 at 11:40 +10 screen off 12:50 +30 at 14:00 = 250."""
    options = {"daily": 180, "weekly": 600, "enabled": True}
    options = add_parent_grant(options, "pc1", at(11, 40), 30)
    if screen:
        options["screen_idle_bonus_journal"] = {
            "version": 1, "device_id": "pc1", "events": [{
                "id": "b" * 32 + ":12", "date": "2026-11-23",
                "minutes": 10, "off_at_utc": at(12, 50).timestamp(),
            }],
        }
    options = add_parent_grant(options, "pc1", at(14), 30)
    data = {
        "ready": ready, "totals": {"daily": used, "weekly": used},
        "coverage_incomplete": False,
    }
    return options, data


def rows(options, data, when=None):
    with patch("custom_components.hal_gaming_control.budget_select.dt_util.as_local",
               side_effect=lambda value: value.astimezone(TZ)):
        return budget_select_rows(options, "pc1", data, when or at())


def selector(*, used=0, ready=True, screen=True, refresh=None):
    options, data = sample_receipt(used=used, ready=ready, screen=screen)
    entry = SimpleNamespace(data={"device_id": "pc1", "name": "Gaming PC"},
                            options=options)
    coordinator = Mock(device_id="pc1", entry=entry, data=data,
                       last_update_success=True)
    coordinator.async_refresh = AsyncMock(side_effect=refresh)
    committed = []

    def save(_entry, *, options):
        committed.append(options)
        entry.options = options

    entity = ParentBonusGrantSelect(coordinator)
    user = SimpleNamespace(is_admin=True)
    auth = SimpleNamespace(async_get_user=AsyncMock(return_value=user))
    entity.hass = SimpleNamespace(
        auth=auth, config_entries=SimpleNamespace(async_update_entry=save))
    entity.async_set_context(Context(user_id="parent-A"))
    return entity, entry, committed


def test_ordered_receipt_shows_only_actionable_red_icons_and_sigma_total():
    options, data = sample_receipt()
    labels = [label for label, _ in rows(options, data)]
    assert labels == [
        "+180min Daily budget",
        "+30min Parent bonus (11:40) ⛔",
        "+10min Screen off bonus (12:50)",
        "+30min Parent bonus (14:00) ⛔",
        "∑ 250min TOTAL",
    ]
    assert all("🔒" not in label for label in labels)
    assert sum(label.endswith("⛔") for label in labels) == 2


@pytest.mark.parametrize("used,unlocked", [
    (180 * 60, 2),
    (180 * 60 + 1, 1),  # One SECOND consumed from oldest bonus.
    (220 * 60, 1),
    (220 * 60 + 1, 0),
    (250 * 60, 0),
])
def test_bonuses_lock_individually_as_usage_reaches_them(used, unlocked):
    options, data = sample_receipt(used=used)
    parent_rows = [(label, grant_id) for label, grant_id in rows(options, data)
                   if "Parent bonus" in label]
    assert len(parent_rows) == 2
    assert sum(label.endswith("⛔") for label, _ in parent_rows) == unlocked
    assert sum(grant_id is not None for _, grant_id in parent_rows) == unlocked


def test_two_parent_bonuses_and_50_minutes_remaining_lock_only_first():
    options, data = sample_receipt(used=190 * 60, screen=False)
    # 180 + 30 + 30 - 190 = 50 minutes.
    labels = [label for label, _ in rows(options, data)]
    assert labels == [
        "+180min Daily budget",
        "+30min Parent bonus (11:40)",
        "+30min Parent bonus (14:00) ⛔",
        "∑ 240min TOTAL",
    ]


@pytest.mark.parametrize("policy", [
    {"enabled": False}, {"unlimited": True}, {"daily": -1},
])
def test_non_finite_policy_cannot_allow_undo(policy):
    options, data = sample_receipt()
    options.update(policy)
    assert all(grant is None for _, grant in rows(options, data))


def test_unknown_usage_locks_all_bonus_actions():
    options, data = sample_receipt(ready=False)
    assert all(grant is None for _, grant in rows(options, data))


@pytest.mark.asyncio
async def test_selecting_one_parent_bonus_immediately_cancels_and_resets_total():
    entity, entry, committed = selector(used=190 * 60, screen=False)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        assert entity.current_option == "∑ 240min TOTAL"
        label = "+30min Parent bonus (14:00) ⛔"
        assert label in entity.options
        await entity.async_select_option(label)
        assert len(committed) == 1
        assert entity.coordinator.async_refresh.await_count == 1
        assert entity.current_option == "∑ 210min TOTAL"
        assert label not in entity.options
        assert parent_bonus_total(entry.options, at()) == 30
        assert sum(e["status"] == "cancelled"
                   for e in parent_bonus_activity_today(entry.options, at())) == 1
        with pytest.raises(HomeAssistantError, match="no longer active"):
            await entity.async_select_option(label)
        assert len(committed) == 1


@pytest.mark.asyncio
async def test_no_action_on_sigma_total_and_non_action_rows_are_rejected():
    entity, _, committed = selector(used=190 * 60, screen=False)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        await entity.async_select_option(entity.current_option)
        for label in ("+180min Daily budget", "+30min Parent bonus (11:40)"):
            with pytest.raises(HomeAssistantError, match="not cancellable"):
                await entity.async_select_option(label)
        assert entity.current_option == "∑ 240min TOTAL"
        assert not committed


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,admin", [
    (None, True), ("child-A", False), ("deleted-user", None),
])
async def test_non_admin_or_anonymous_select_cannot_revoke(user_id, admin):
    entity, entry, committed = selector(used=190 * 60, screen=False)
    if user_id is None:
        entity.async_set_context(Context())
    elif admin is None:
        entity.hass.auth.async_get_user.return_value = None
        entity.async_set_context(Context(user_id=user_id))
    else:
        entity.hass.auth.async_get_user.return_value = SimpleNamespace(
            is_admin=admin)
        entity.async_set_context(Context(user_id=user_id))
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        with pytest.raises(HomeAssistantError, match="administrator"):
            await entity.async_select_option("+30min Parent bonus (14:00) ⛔")
        assert entity.current_option == "∑ 240min TOTAL"
        assert not committed
        assert parent_bonus_total(entry.options, at()) == 60


@pytest.mark.asyncio
async def test_spending_one_second_while_dropdown_open_rejects_stale_action():
    entity, entry, committed = selector(used=220 * 60)
    entity.coordinator.async_refresh = AsyncMock(
        side_effect=lambda: entity.coordinator.data["totals"].update(
            {"daily": 220 * 60 + 1}))
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        label = "+30min Parent bonus (14:00) ⛔"
        assert label in entity.options
        with pytest.raises(HomeAssistantError, match="used or budget changed"):
            await entity.async_select_option(label)
        assert entity.current_option == "∑ 250min TOTAL"
        assert parent_bonus_total(entry.options, at()) == 60
        assert not committed


@pytest.mark.asyncio
async def test_exactly_zero_remaining_after_cancel_is_allowed():
    entity, entry, committed = selector(used=210 * 60, screen=False)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        # The last Parent is untouched; removing it leaves 210-210 = 0.
        await entity.async_select_option("+30min Parent bonus (14:00) ⛔")
        assert len(committed) == 1
        assert entity.current_option == "∑ 210min TOTAL"
        assert parent_bonus_total(entry.options, at()) == 30


@pytest.mark.asyncio
async def test_failed_save_never_claims_undo_succeeded():
    entity, entry, committed = selector(used=190 * 60, screen=False)
    entity.hass.config_entries.async_update_entry = Mock(return_value=False)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        with pytest.raises(HomeAssistantError, match="not saved"):
            await entity.async_select_option("+30min Parent bonus (14:00) ⛔")
        assert not committed
        assert parent_bonus_total(entry.options, at()) == 60


@pytest.mark.asyncio
async def test_date_rollover_rechecks_after_refresh():
    entity, entry, committed = selector(used=190 * 60, screen=False)
    times = iter([at(), at(), at(), at(), at(), at(15, 1)])
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               side_effect=lambda: next(times, at(15, 1))), patch.object(
                   entity, "async_write_ha_state"):
        # After refresh, advancing within the same day still works.
        await entity.async_select_option("+30min Parent bonus (14:00) ⛔")
        assert len(committed) == 1
