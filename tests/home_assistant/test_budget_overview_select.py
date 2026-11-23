"""Native Budget receipt with immediate, administrator-only Parent Undo."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.hal_gaming_control.budget_select import (
    DIVIDER_TOP, DIVIDER_BOTTOM, budget_select_rows,
)
from custom_components.hal_gaming_control.parent_bonus import (
    add_parent_grant, parent_bonus_activity_today, parent_bonus_total,
)
from custom_components.hal_gaming_control.select import ParentBonusGrantSelect

TZ = ZoneInfo("Europe/Zagreb")
FIGURE = "\u2007"


def amount(minutes, title, width=3):
    return f"+{FIGURE}{str(minutes).rjust(width, FIGURE)} min - {title}"


def action(minutes, title):
    return amount(minutes, title) + FIGURE * 6 + "⛔"


def total(minutes):
    return f"∑{FIGURE}{minutes} min - TOTAL"


def played(minutes):
    return f"-{FIGURE}{str(minutes).rjust(3, FIGURE)} min - Gaming Session"


def remaining(minutes):
    return f"∑{FIGURE}{str(minutes).rjust(3, FIGURE)} min - Remaining Budget"


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
        amount(180, "Daily Budget"),
        action(30, "Parent Bonus (11:40)"),
        amount(10, "Screen Off Bonus (12:50)"),
        action(30, "Parent Bonus (14:00)"),
        DIVIDER_TOP,
        total(250),
        played(0),
        DIVIDER_BOTTOM,
        remaining(250),
    ]
    assert all("🔒" not in label for label in labels)
    assert all("⛔" not in label for label in labels if "Parent Bonus" not in label)
    assert all(FIGURE in label for label in labels
               if label not in (DIVIDER_TOP, DIVIDER_BOTTOM))
    assert all("1234567890" not in label for label in labels)
    assert sum(label.endswith("⛔") for label in labels) == 2
    assert len(labels) == len(set(labels))  # HA Select option uniqueness
    assert labels[-1] == remaining(250)
    assert sum("─" in label for label in labels) == 2


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
                   if "Parent Bonus" in label]
    assert len(parent_rows) == 2
    assert sum(label.endswith("⛔") for label, _ in parent_rows) == unlocked
    assert sum(grant_id is not None for _, grant_id in parent_rows) == unlocked


def test_two_parent_bonuses_and_50_minutes_remaining_lock_only_first():
    options, data = sample_receipt(used=190 * 60, screen=False)
    # 180 + 30 + 30 - 190 = 50 minutes.
    labels = [label for label, _ in rows(options, data)]
    assert labels == [
        amount(180, "Daily Budget"),
        amount(30, "Parent Bonus (11:40)"),
        action(30, "Parent Bonus (14:00)"),
        DIVIDER_TOP,
        total(240),
        played(190),
        DIVIDER_BOTTOM,
        remaining(50),
    ]



@pytest.mark.parametrize("seconds,expected_played,expected_remaining", [
    (0, 0, 240),
    (1, 1, 239),
    (59.1, 1, 239),
    (60, 1, 239),
    (61, 2, 238),
    (190 * 60, 190, 50),
    (240 * 60 - 1, 240, 0),
    (240 * 60, 240, 0),
    (250 * 60, 250, 0),
])
def test_receipt_reconciles_conservative_whole_minutes(
        seconds, expected_played, expected_remaining):
    options, data = sample_receipt(used=seconds, screen=False)
    labels = [label for label, _ in rows(options, data)]
    assert labels[-3] == played(expected_played)
    assert labels[-1] == remaining(expected_remaining)
    assert labels[-4] == total(240)


def test_unverified_time_is_never_misrepresented_as_zero():
    options, data = sample_receipt(screen=False)
    data["ready"] = False
    lines = rows(options, data)
    assert lines[-3] == ("- Unknown - Gaming Session", None)
    assert lines[-1] == ("∑ Unknown - Remaining Budget", None)
    assert all(grant is None for _, grant in lines)
    data["ready"] = True
    data["totals"] = {}
    assert rows(options, data)[-1] == ("∑ Unknown - Remaining Budget", None)


@pytest.mark.parametrize("policy,final_label", [
    ({"enabled": False}, "∑ Rules Disabled - Remaining Budget"),
    ({"unlimited": True}, "∑ Unlimited - Remaining Budget"),
    ({"daily": -1}, "∑ Unlimited - Remaining Budget"),
])
def test_no_fake_numeric_remaining_when_rules_disabled_or_unlimited(
        policy, final_label):
    options, data = sample_receipt(used=120 * 60, screen=False)
    options.update(policy)
    labels = [label for label, _ in rows(options, data)]
    assert labels[-3] == played(120)
    assert labels[-1] == final_label


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
        assert entity.current_option == remaining(50)
        label = action(30, "Parent Bonus (14:00)")
        assert label in entity.options
        await entity.async_select_option(label)
        assert len(committed) == 1
        assert entity.coordinator.async_refresh.await_count == 1
        assert entity.current_option == remaining(20)
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
        for label in (amount(180, "Daily Budget"),
                      amount(30, "Parent Bonus (11:40)"),
                      DIVIDER_TOP, total(240), played(190), DIVIDER_BOTTOM):
            await entity.async_select_option(label)
            assert entity.current_option == remaining(50)
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
            await entity.async_select_option(action(30, "Parent Bonus (14:00)"))
        assert entity.current_option == remaining(50)
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
        label = action(30, "Parent Bonus (14:00)")
        assert label in entity.options
        with pytest.raises(HomeAssistantError, match="used or budget changed"):
            await entity.async_select_option(label)
        assert entity.current_option == remaining(30)
        assert parent_bonus_total(entry.options, at()) == 60
        assert not committed


@pytest.mark.asyncio
async def test_exactly_zero_remaining_after_cancel_is_allowed():
    entity, entry, committed = selector(used=210 * 60, screen=False)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        # The last Parent is untouched; removing it leaves 210-210 = 0.
        await entity.async_select_option(action(30, "Parent Bonus (14:00)"))
        assert len(committed) == 1
        assert entity.current_option == remaining(0)
        assert parent_bonus_total(entry.options, at()) == 30


@pytest.mark.asyncio
async def test_failed_save_never_claims_undo_succeeded():
    entity, entry, committed = selector(used=190 * 60, screen=False)
    entity.hass.config_entries.async_update_entry = Mock(return_value=False)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        with pytest.raises(HomeAssistantError, match="not saved"):
            await entity.async_select_option(action(30, "Parent Bonus (14:00)"))
        assert not committed
        assert parent_bonus_total(entry.options, at()) == 60


@pytest.mark.asyncio
async def test_date_rollover_before_fresh_check_cannot_revoke_yesterday_grant():
    entity, entry, committed = selector(used=190 * 60, screen=False)
    today, tomorrow = at(), at().replace(day=24)
    times = iter([today, tomorrow])
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               side_effect=lambda: next(times, tomorrow)), patch.object(
                   entity, "async_write_ha_state"):
        with pytest.raises(HomeAssistantError, match="used or budget changed"):
            await entity.async_select_option(action(30, "Parent Bonus (14:00)"))
        assert not committed
        assert parent_bonus_total(entry.options, today) == 60
