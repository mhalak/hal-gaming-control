"""Issue #165: safe native HA Parent bonus undo workflow."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.hal_gaming_control.parent_bonus import (
    add_parent_grant, parent_bonus_activity_today, parent_bonus_total,
)
from custom_components.hal_gaming_control.select import (
    ParentBonusGrantSelect, UNSELECTED,
)

TZ = ZoneInfo("Europe/Zagreb")


def at(hour=14, minute=30, day=22):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def setup_select():
    opts = {"enabled": True, "daily": 120, "weekly": 300}
    for i in range(3):
        opts = add_parent_grant(opts, "pc1", at(minute=i + 1), 30)
    entry = SimpleNamespace(data={"device_id": "pc1", "name": "Gaming PC"},
                            options=opts)
    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry = entry
    coordinator.data = {"ready": False}
    coordinator.last_update_success = True
    committed = []

    def save(_entry, *, options):
        committed.append(options)
        entry.options = options

    entity = ParentBonusGrantSelect(coordinator)
    entity.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=save))
    return entity, entry, committed


@pytest.mark.asyncio
async def test_native_select_lists_each_grant_without_manual_ids():
    entity, entry, committed = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        options = entity.options
        assert options[0] == UNSELECTED
        assert len(options) == 4
        assert len(set(options)) == 4
        assert "30 min" in options[1]
        assert entity.current_option == UNSELECTED
        await entity.async_select_option(options[2])
        assert entity.current_option == options[2]
        assert not committed
        assert parent_bonus_total(entry.options, at()) == 90


@pytest.mark.asyncio
async def test_prepare_confirm_revokes_only_selected_grant_and_preserves_history():
    entity, entry, committed = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch(
                   "custom_components.hal_gaming_control.select.monotonic",
                   return_value=150.0), patch.object(entity, "async_write_ha_state"):
        picked = entity.options[2]
        await entity.async_select_option(picked)
        entity.prepare("parent-A")
        assert len(committed) == 0
        assert entity.extra_state_attributes["prepared_grant"] == picked
        entity.confirm("parent-A")
        assert len(committed) == 1
        assert parent_bonus_total(entry.options, at()) == 60
        assert len([e for e in parent_bonus_activity_today(entry.options, at())
                    if e["status"] == "cancelled"]) == 1
        assert entity.current_option == UNSELECTED
        with pytest.raises(HomeAssistantError):
            entity.confirm("parent-A")


@pytest.mark.asyncio
async def test_other_parent_cannot_confirm_a_pending_grant():
    entity, entry, commits = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch(
                   "custom_components.hal_gaming_control.select.monotonic",
                   return_value=150.0), patch.object(entity, "async_write_ha_state"):
        await entity.async_select_option(entity.options[1])
        entity.prepare("parent-A")
        with pytest.raises(HomeAssistantError, match="your own"):
            entity.confirm("parent-B")
        assert not commits
        entity.confirm("parent-A")
        assert len(commits) == 1


@pytest.mark.asyncio
async def test_interleaved_selection_invalidates_prepared_undo():
    entity, entry, commits = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch(
                   "custom_components.hal_gaming_control.select.monotonic",
                   return_value=150.0), patch.object(entity, "async_write_ha_state"):
        await entity.async_select_option(entity.options[1])
        entity.prepare("parent-A")
        await entity.async_select_option(entity.options[2])
        with pytest.raises(HomeAssistantError):
            entity.confirm("parent-A")
        assert not commits


@pytest.mark.asyncio
async def test_preparation_expires_and_does_not_survive_restart():
    entity, entry, commits = setup_select()
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        with patch("custom_components.hal_gaming_control.select.monotonic",
                   return_value=1.0):
            await entity.async_select_option(entity.options[1])
            entity.prepare("parent-A")
        with patch("custom_components.hal_gaming_control.select.monotonic",
                   return_value=100.0):
            with pytest.raises(HomeAssistantError, match="expired"):
                entity.confirm("parent-A")
        assert not commits
        fresh = ParentBonusGrantSelect(entity.coordinator)
        fresh.hass = entity.hass
        with patch("custom_components.hal_gaming_control.select.monotonic",
                   return_value=1.0):
            with pytest.raises(HomeAssistantError):
                fresh.confirm("parent-A")


@pytest.mark.asyncio
async def test_date_rollover_and_stale_grant_are_rejected():
    entity, entry, commits = setup_select()
    with patch.object(entity, "async_write_ha_state"), patch(
        "custom_components.hal_gaming_control.select.monotonic",
        return_value=100.0,
    ):
        with patch("custom_components.hal_gaming_control.select.dt_util.now",
                   return_value=at()):
            await entity.async_select_option(entity.options[1])
            entity.prepare("parent-A")
        with patch("custom_components.hal_gaming_control.select.dt_util.now",
                   return_value=at(day=23)):
            with pytest.raises(HomeAssistantError):
                entity.confirm("parent-A")
        assert not commits


@pytest.mark.asyncio
async def test_no_success_when_save_fails():
    entity, entry, commits = setup_select()
    def broken(*args, **kwargs):
        raise RuntimeError("storage error")
    entity.hass.config_entries.async_update_entry = broken
    with patch.object(entity, "async_write_ha_state"), patch(
        "custom_components.hal_gaming_control.select.monotonic",
        return_value=100.0,
    ), patch("custom_components.hal_gaming_control.select.dt_util.now",
             return_value=at()):
        await entity.async_select_option(entity.options[1])
        entity.prepare("parent-A")
        with pytest.raises(RuntimeError, match="storage"):
            entity.confirm("parent-A")
        assert parent_bonus_total(entry.options, at()) == 90
        assert "Cancelled" not in entity.extra_state_attributes.get("undo_status", "")


@pytest.mark.asyncio
async def test_ha_services_are_admin_only_target_one_real_select(hass):
    from homeassistant.auth.const import GROUP_ID_ADMIN
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized
    from custom_components.hal_gaming_control.const import DOMAIN
    from custom_components.hal_gaming_control.services import async_setup_services

    entity, entry, committed = setup_select()
    entity.hass = hass
    def save(_entry, *, options):
        entry.options = options
        committed.append(options)

    with patch.object(hass.config_entries, "async_update_entry", side_effect=save):
        hass.data[DOMAIN] = {"parent_bonus_undo_selects": {
            "select.pc1_parent_bonus_to_undo": entity,
        }}
        async_setup_services(hass)
        admin = await hass.auth.async_create_user(
            "Parent admin", group_ids=[GROUP_ID_ADMIN])
        other = await hass.auth.async_create_user("Child")

        with patch("custom_components.hal_gaming_control.select.dt_util.now",
                   return_value=at()), patch(
                       "custom_components.hal_gaming_control.select.monotonic",
                       return_value=250.0), patch.object(entity, "async_write_ha_state"):
            await entity.async_select_option(entity.options[1])
            target = {"entity_id": "select.pc1_parent_bonus_to_undo"}
            for who in (other.id, None):
                with pytest.raises((Unauthorized, HomeAssistantError)):
                    await hass.services.async_call(
                        DOMAIN, "prepare_parent_bonus_undo", target,
                        blocking=True, context=Context(user_id=who))
            assert not committed
            await hass.services.async_call(
                DOMAIN, "prepare_parent_bonus_undo", target, blocking=True,
                context=Context(user_id=admin.id))
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    DOMAIN, "confirm_parent_bonus_undo",
                    {"entity_id": "select.other_pc_parent_bonus_to_undo"},
                    blocking=True, context=Context(user_id=admin.id))
            assert not committed
            await hass.services.async_call(
                DOMAIN, "confirm_parent_bonus_undo", target, blocking=True,
                context=Context(user_id=admin.id))
        assert len(committed) == 1
        assert parent_bonus_total(entry.options, at()) == 60
