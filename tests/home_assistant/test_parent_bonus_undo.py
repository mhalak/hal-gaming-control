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
        assert entity.current_option == f"∑{FIGURE * 2}75 min - TOTAL"
        assert entry.options["parent_bonus_journal"]["events"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_penalty_undo_requires_admin_and_restores_only_selected_record():
    from custom_components.hal_gaming_control.gaming_penalty import add_penalty, active_penalties

    entity, entry, committed = setup_select()
    entry.options = add_penalty(entry.options, "pc1", at(minute=10),
                                minutes=30, remaining_seconds=12600)
    entry.options = add_penalty(entry.options, "pc1", at(minute=11),
                                cancel_today=True)
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        label = next(row for row in entity.options if "Gaming cancelled today" in row)
        assert label.endswith("⛔")
        entity.async_set_context(Context(user_id="child"))
        entity.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=False)
        with pytest.raises(HomeAssistantError, match="administrator"):
            await entity.async_select_option(label)
        assert not committed
        entity.async_set_context(Context(user_id="parent-A"))
        entity.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=True)
        await entity.async_select_option(label)
        assert len(committed) == 1
        remaining = active_penalties(entry.options, "pc1", at())
        assert len(remaining) == 1 and remaining[0]["seconds"] == 1800
        assert parent_bonus_total(entry.options, at()) == 90
        assert entity.current_option == total(180)


@pytest.mark.asyncio
async def test_new_penalty_switch_and_button_reject_non_admin_context():
    from custom_components.hal_gaming_control.button import GamingPenaltyButton
    from custom_components.hal_gaming_control.switch import GamingSuspendedSwitch

    entity, entry, committed = setup_select()
    coordinator = entity.coordinator
    coordinator.options = entry.options
    suspended = GamingSuspendedSwitch(coordinator)
    cancel = GamingPenaltyButton(coordinator, True)
    for control, action in ((suspended, suspended.async_turn_on),
                            (cancel, cancel.async_press)):
        control.hass = entity.hass
        for context in (Context(), Context(user_id="child")):
            control.async_set_context(context)
            control.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=False)
            with pytest.raises(HomeAssistantError, match="administrator"):
                await action()
    assert not committed
    suspended.async_set_context(Context(user_id="parent-A"))
    suspended.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=True)
    with patch.object(suspended, "async_write_ha_state"):
        await suspended.async_turn_on()
        assert entry.options["gaming_suspended"] is True
        await suspended.async_turn_off()
        assert entry.options["gaming_suspended"] is False
    cancel.async_set_context(Context(user_id="parent-A"))
    await cancel.async_press()
    assert entry.options["gaming_penalty_journal"]["events"][-1]["cancel_today"] is True
    assert len(committed) == 3


def test_sync_bonus_exact_seconds_and_only_positive_difference():
    from custom_components.hal_gaming_control.bonus_sync import sync_difference
    assert sync_difference("pc1", {"pc1": 1800, "pc2": 2250}) == 450
    assert sync_difference("pc1", {"pc1": 1800, "pc2": 1801}) == 1
    assert sync_difference("pc1", {"pc1": 1800, "pc2": 1800}) == 0
    assert sync_difference("pc1", {"pc1": 2250, "pc2": 1800}) == 0
    assert sync_difference("pc1", {"pc1": 0}) == 0
    assert sync_difference("pc1", {"pc1": 10, "pc2": 100, "pc3": 80}) == 90
    for invalid in ({"pc2": 10}, {"pc1": 0, "pc2": None},
                    {"pc1": 0, "pc2": True}, {"pc1": 0, "pc2": -1},
                    {"pc1": 0, "pc2": 0.5}, {"pc1": 0, "pc2": 36001}):
        with pytest.raises(ValueError):
            sync_difference("pc1", invalid)


def test_sync_entitlement_counts_active_parent_grants_once_and_excludes_overrides():
    from custom_components.hal_gaming_control.bonus_sync import bonus_entitlement_seconds
    from custom_components.hal_gaming_control.parent_bonus import revoke_parent_grant
    options = {"bonus_date": "2026-11-23", "bonus_minutes": 5,
               "daily": 180, "weekend_bonus": 60, "unlimited": True,
               "gaming_suspended": True,
               "screen_idle_bonus_journal": {"version": 1, "device_id": "pc1",
                   "events": [{"id": "receipt", "date": "2026-11-23",
                               "minutes": 7, "off_at_utc": at().timestamp()}]}}
    options = add_parent_grant(options, "pc1", at(minute=1), 30)
    options = add_parent_grant(options, "pc1", at(minute=2), 10)
    cancelled = options["parent_bonus_journal"]["events"][-1]["id"]
    options = revoke_parent_grant(options, "pc1", cancelled, at(minute=3))
    assert bonus_entitlement_seconds(options, "pc1", at()) == 2520
    assert bonus_entitlement_seconds(options, "pc1", at(day=24)) == 0
    with pytest.raises(ValueError):
        bonus_entitlement_seconds(options, "pc2", at())
    with pytest.raises(ValueError):
        bonus_entitlement_seconds(options | {"screen_idle_bonus_journal": {"version": 99}},
                                  "pc1", at())


def test_exact_sync_grant_replays_legacy_and_preserves_second_precision():
    import json
    from custom_components.hal_gaming_control.smart_bonus_transaction import (
        prepare_grant, prepare_sync_grant, cancel_grant)
    from custom_components.hal_gaming_control.parent_bonus import grant_seconds
    from custom_components.hal_gaming_control.bonus_sync import bonus_entitlement_seconds
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot

    settings = {"enabled": True, "daily": 120, "weekly": 300}
    totals = {"daily": 0, "weekly": 0, "per_game": {}}
    base = {"daily": 7200, "weekly": 18000}
    manual = prepare_grant(settings, "pc1", at(minute=1), 30, base)
    exact = prepare_sync_grant(manual, "pc1", at(minute=2), 450, base)
    exact = prepare_sync_grant(exact, "pc1", at(minute=3), 1, base)
    persisted = json.loads(json.dumps(exact))
    events = persisted["parent_bonus_journal"]["events"]
    assert [grant_seconds(row) for row in events] == [1800, 450, 1]
    assert events[1]["source"] == "sync" and events[2]["source"] == "sync"
    assert persisted["bonus_minutes"] == 0
    assert bonus_entitlement_seconds(persisted, "pc1", at()) == 2251
    assert effective_snapshot(persisted, totals, at(), "pc1", ready=True).selection.remaining_seconds == 9451
    undone = cancel_grant(persisted, "pc1", events[1]["id"], at())
    assert bonus_entitlement_seconds(undone, "pc1", at()) == 1801
    assert effective_snapshot(undone, totals, at(), "pc1", ready=True).selection.remaining_seconds == 9001
    assert bonus_entitlement_seconds(persisted, "pc1", at()) == 2251
    for value in (0, -1, True, 1.5, 36001):
        with pytest.raises(ValueError):
            prepare_sync_grant(manual, "pc1", at(minute=2), value, base)


@pytest.mark.asyncio
async def test_exact_sync_receipt_displays_granted_seconds_and_can_undo():
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_sync_grant
    from custom_components.hal_gaming_control.bonus_sync import bonus_entitlement_seconds
    entity, entry, committed = setup_select()
    settings = {"enabled": True, "daily": 120, "weekly": 300}
    entry.options = prepare_sync_grant(settings, "pc1", at(minute=1), 450,
                                       {"daily": 7200, "weekly": 18000})
    with patch("custom_components.hal_gaming_control.select.dt_util.now",
               return_value=at()), patch.object(entity, "async_write_ha_state"):
        label = next(row for row in entity.options if "Sync Bonus" in row)
        assert "7m 30s" in label and label.endswith("⛔")
        await entity.async_select_option(label)
        assert len(committed) == 1
        assert bonus_entitlement_seconds(entry.options, "pc1", at()) == 0
        assert entity.current_option == total(120)


def test_sync_journal_rejects_downgrade_and_inconsistent_exact_amount():
    from copy import deepcopy
    from custom_components.hal_gaming_control.smart_bonus_transaction import prepare_sync_grant
    from custom_components.hal_gaming_control.parent_bonus import _journal, JOURNAL_KEY
    from custom_components.hal_gaming_control.bonus_sync import bonus_entitlement_seconds

    exact = prepare_sync_grant({"enabled": True, "daily": 120, "weekly": 300},
                               "pc1", at(), 1, {"daily": 7200, "weekly": 18000})
    assert _journal(exact)["version"] == 2
    assert bonus_entitlement_seconds(exact, "pc1", at()) == 1
    for change in ({"amount_seconds": True}, {"amount_seconds": 0},
                   {"minutes": 1}, {"source": "unknown"}):
        bad = deepcopy(exact)
        bad[JOURNAL_KEY]["events"][0].update(change)
        with pytest.raises(ValueError):
            _journal(bad)
    bad = deepcopy(exact)
    bad[JOURNAL_KEY]["version"] = 1
    with pytest.raises(ValueError):
        _journal(bad)


@pytest.mark.asyncio
async def test_sync_button_requires_admin_context():
    from custom_components.hal_gaming_control.button import SyncBonusButton
    entity, entry, committed = setup_select()
    control = SyncBonusButton(entity.coordinator)
    control.hass = entity.hass
    with patch("custom_components.hal_gaming_control.button.async_sync_bonus", new_callable=AsyncMock) as sync:
        control.async_set_context(Context(user_id="child"))
        control.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=False)
        with pytest.raises(HomeAssistantError, match="administrator"):
            await control.async_press()
        sync.assert_not_awaited()
        control.async_set_context(Context(user_id="parent-A"))
        control.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=True)
        await control.async_press()
        sync.assert_awaited_once_with(control.hass, entity.coordinator)
    assert not committed


def test_sync_bonus_uses_verified_unlimited_credit_without_copying_it():
    from custom_components.hal_gaming_control.smart_parent_control import prepare_live_sync_grant
    from custom_components.hal_gaming_control.smart_policy import effective_snapshot
    from custom_components.hal_gaming_control.smart_receipt import smart_receipt
    from custom_components.hal_gaming_control.bonus_sync import bonus_entitlement_seconds

    settings = {"enabled": True, "daily": 120, "weekly": 300}
    totals = {"daily": 3600, "weekly": 3600, "per_game": {},
              "unlimited_bonus": {"daily": 1800, "weekly": 1800, "per_game": {}}}
    options = prepare_live_sync_grant(settings, "pc1", at(), 450, totals, ready=True)
    snapshot = effective_snapshot(options, totals, at(), "pc1", ready=True)
    assert snapshot.selection.remaining_seconds == 5850
    assert bonus_entitlement_seconds(options, "pc1", at()) == 450
    receipt = smart_receipt(options, totals, at(), "pc1", snapshot, ())
    assert receipt.remaining == 5850
    assert any(row.title == "Unlimited Bonus" and row.seconds == 1800
               for row in receipt.lines)
    assert any("Sync Bonus" in row.title and row.seconds == 450
               for row in receipt.lines)
