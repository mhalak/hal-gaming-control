"""Native parent grant selection is instant, scoped and auditable."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.hal_gaming_control.const import DOMAIN
from custom_components.hal_gaming_control.parent_bonus import (
    add_parent_grant, parent_bonus_activity_today, parent_bonus_total,
)
from custom_components.hal_gaming_control.select import ParentBonusGrantSelect

TZ = ZoneInfo("Europe/Zagreb")
FIGURE = "\u2007"


def total(minutes):
    return f"∑{FIGURE}{minutes} min - TOTAL"


def at(hour=14, minute=30, day=23):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def setup_select():
    options = {"enabled": True, "daily": 120, "weekly": 300}
    for i in range(3):
        options = add_parent_grant(options, "pc1", at(minute=i + 1), 30)
    entry = SimpleNamespace(data={"device_id": "pc1", "name": "Gaming PC"},
                            options=options)
    coordinator = Mock(device_id="pc1", entry=entry, last_update_success=True)
    coordinator.data = {"ready": True,
                        "totals": {"daily": 0, "weekly": 0},
                        "coverage_incomplete": False}
    coordinator.async_refresh = AsyncMock()
    committed = []

    def save(_entry, *, options):
        committed.append(options)
        entry.options = options

    entity = ParentBonusGrantSelect(coordinator)
    entity.hass = SimpleNamespace(
        auth=SimpleNamespace(
            async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=True))),
        config_entries=SimpleNamespace(async_update_entry=save))
    entity.async_set_context(Context(user_id="parent-A"))
    return entity, entry, committed


@pytest.mark.asyncio
async def test_parent_undo_is_one_step_and_keeps_full_audit():
    entity, entry, committed = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        assert entity.current_option == total(210)
        parent_labels = [label for label in entity.options if "Parent Bonus" in label]
        assert len(parent_labels) == 3
        assert all(label.endswith("⛔") for label in parent_labels)
        assert all("🔒" not in label for label in entity.options)

        await entity.async_select_option(parent_labels[1])
        assert len(committed) == 1
        assert parent_bonus_total(entry.options, at()) == 60
        assert entity.current_option == total(180)
        assert parent_labels[1] not in entity.options
        activity = parent_bonus_activity_today(entry.options, at())
        assert sum(row["status"] == "cancelled" for row in activity) == 1
        assert sum(row["status"] == "active" for row in activity) == 2
        assert "Cancelled:" in entity.extra_state_attributes["undo_status"]


@pytest.mark.asyncio
async def test_same_minute_grants_have_unique_labels_and_exact_ids():
    entity, entry, committed = setup_select()
    for _ in range(2):
        entry.options = add_parent_grant(entry.options, "pc1",
                                         at(hour=11, minute=40), 30)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch(
                   "custom_components.hal_gaming_control.budget_select.dt_util.as_local",
                   side_effect=lambda stamp: stamp.astimezone(TZ)), patch.object(
                       entity, "async_write_ha_state"):
        choices = entity._choices(at())
        ambiguous = [name for name in choices
                     if "Parent Bonus (11:40" in name]
        assert len(ambiguous) == 2
        assert len(set(ambiguous)) == 2
        assert all(name.endswith("⛔") for name in ambiguous)
        assert any("(11:40 #1)" in name for name in ambiguous)
        assert any("(11:40 #2)" in name for name in ambiguous)
        assert all(choices[name] not in name for name in ambiguous)
        assert all(choices[name][-10:] not in name for name in ambiguous)
        picked, grant_id = ambiguous[0], choices[ambiguous[0]]
        await entity.async_select_option(picked)
        assert len(committed) == 1
        activity = parent_bonus_activity_today(entry.options, at())
        assert next(item for item in activity if item["id"] == grant_id)[
            "status"] == "cancelled"
        assert sum(item["status"] == "active" for item in activity) == 4
        assert entity.current_option == total(240)


def test_same_minute_internal_id_collision_never_exposes_ids():
    entity, entry, _ = setup_select()
    for _ in range(2):
        entry.options = add_parent_grant(entry.options, "pc1",
                                         at(hour=11, minute=40), 30)
    events = entry.options["parent_bonus_journal"]["events"]
    events[-2]["id"] = "a" * 22 + "1234567890"
    events[-1]["id"] = "b" * 22 + "1234567890"
    with patch("custom_components.hal_gaming_control.budget_select.dt_util.as_local",
               side_effect=lambda stamp: stamp.astimezone(TZ)):
        choices = entity._choices(at())
    ambiguous = [label for label in choices
                 if "Parent Bonus (11:40" in label]
    assert len(ambiguous) == 2
    assert any("(11:40 #1)" in label for label in ambiguous)
    assert any("(11:40 #2)" in label for label in ambiguous)
    assert all(choices[label] not in label for label in ambiguous)
    assert all(choices[label][-10:] not in label for label in ambiguous)
    assert len(set(ambiguous)) == 2


@pytest.mark.asyncio
async def test_wrong_device_grant_never_cancelled():
    entity, entry, committed = setup_select()
    # A foreign journal record is invalid for this device and must not be
    # removable; no guessed grant IDs can bypass the dropdown choices.
    entry.options["parent_bonus_journal"]["events"][-1]["device_id"] = "pc2"
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        foreign_id = entry.options["parent_bonus_journal"]["events"][-1]["id"]
        label = next(label for label, grant_id in entity._choices(at()).items()
                     if grant_id == foreign_id)
        # The journal is still displayed but neither device scope nor
        # append-only audit fields can be circumvented in revoke_parent_grant.
        with pytest.raises(HomeAssistantError, match="another device"):
            await entity.async_select_option(label)
        assert not committed


@pytest.mark.asyncio
async def test_replay_selection_does_not_cancel_other_grants():
    entity, entry, committed = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        label = next(label for label in entity.options if label.endswith("⛔"))
        await entity.async_select_option(label)
        with pytest.raises(HomeAssistantError):
            await entity.async_select_option(label)
        assert len(committed) == 1
        assert parent_bonus_total(entry.options, at()) == 60


@pytest.mark.asyncio
async def test_admin_user_context_required_for_select_on_ha_devices():
    entity, entry, committed = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        label = next(label for label in entity.options if label.endswith("⛔"))
        for context, identity in ((Context(user_id="child"), False),
                                  (Context(), None)):
            entity.async_set_context(context)
            if identity is False:
                entity.hass.auth.async_get_user.return_value = (
                    SimpleNamespace(is_admin=False))
            with pytest.raises(HomeAssistantError, match="administrator"):
                await entity.async_select_option(label)
        assert not committed
        assert parent_bonus_total(entry.options, at()) == 90


@pytest.mark.asyncio
async def test_old_prepare_confirm_ha_services_are_gone(hass):
    from custom_components.hal_gaming_control import async_setup
    assert await async_setup(hass, {})
    assert not hass.services.has_service(DOMAIN, "prepare_parent_bonus_undo")
    assert not hass.services.has_service(DOMAIN, "confirm_parent_bonus_undo")


@pytest.mark.asyncio
async def test_smart_receipt_dropdown_undo_routes_through_replay():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_grant
    entity, entry, committed = setup_select()
    stamp = at(hour=21, minute=45)
    settings = {"enabled": True, "unlimited": False, "daily": 180, "weekly": 300,
                "schedule_enabled": True, "schedule_start": "16:00", "schedule_end": "22:00"}
    entry.options = prepare_grant(settings, "pc1", stamp, 30,
                                  {"daily": 7200, "weekly": 14400}, settings)
    entity.coordinator.data["totals"] = {"daily": 3600, "weekly": 3600}
    entity.coordinator.foreground.export_segments.return_value = ()
    with patch("custom_components.hal_gaming_control.select.dt_util.now", return_value=stamp), \
         patch.object(entity, "async_write_ha_state"):
        assert entity.current_option == total(105)
        assert any("Until Schedule Limit" in row for row in entity.options)
        choice = next(row for row in entity.options if "Parent Bonus" in row)
        assert choice.endswith("⛔")
        await entity.async_select_option(choice)
        assert len(committed) == 1
        assert entity.current_option == total(75)
        assert entry.options["parent_bonus_journal"]["events"][0]["status"] == "cancelled"
