"""Runtime tests for Recorder downtime accounting using the REAL in-memory Recorder.

The single mechanism is uptime-heartbeat coverage (``coverage.py``, PR #8): gaming time is
counted only between consecutive, consistent ``uptime`` heartbeats, so any outage (HA, Recorder
or broker) longer than the 90 s heartbeat tolerance is unobserved and contributes 0.
States are written through the real state machine (``hass.states.async_set``) and read back
through the real ``history.state_changes_during_period``. A Home Assistant outage is modelled
exactly as the Recorder sees it: no rows (and therefore no heartbeats) while HA is down.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import AsyncMock, patch
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_block_recorder, async_wait_recording_done)

from custom_components.smarthouse_gaming.const import DOMAIN
from custom_components.smarthouse_gaming.coordinator import GamingCoordinator

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]

TZ = ZoneInfo("Europe/Zagreb")
DATA = {"device_id": "pc1", "name": "Gaming PC 1", "protocol_version": 1,
        "games": ["Minecraft", "Roblox"], "actions": ["terminate_game", "lock_pc"]}
H, M = 3600, 60
UPTIME0 = 100_000


def at(month, day, hour=0, minute=0, second=0, fold=0):
    return datetime(2026, month, day, hour, minute, second, tzinfo=TZ, fold=fold)


def ts(*args, **kwargs):
    return at(*args, **kwargs).timestamp()


class Rig:
    def __init__(self, hass, freezer):
        self.hass, self.freezer = hass, freezer
        self.created = []
        self.entry = MockConfigEntry(domain=DOMAIN, title="Gaming PC 1", data=DATA,
                                     unique_id="pc1")
        self.entry.add_to_hass(hass)
        reg = er.async_get(hass)
        self.source = reg.async_get_or_create(
            "sensor", "mqtt", "smarthouse_gaming_pc1_current_game",
            suggested_object_id="pc1_current_game").entity_id
        self.uptime = reg.async_get_or_create(
            "sensor", "mqtt", "smarthouse_gaming_pc1_uptime",
            suggested_object_id="pc1_uptime").entity_id
        self.in_game = reg.async_get_or_create(
            "binary_sensor", "mqtt", "smarthouse_gaming_pc1_in_game",
            suggested_object_id="pc1_in_game").entity_id

    async def beats(self, start, end, step=M, wait=True):
        """Windows heartbeats: the uptime counter keeps counting in real time, 1 row per step."""
        for when in range(int(start), int(end) + 1, step):
            self.hass.states.async_set(self.uptime, str(UPTIME0 + when - int(ts(9, 1))),
                                       timestamp=when)
        if wait:
            await async_wait_recording_done(self.hass)
        else:
            await self.hass.async_block_till_done()

    async def state(self, entity, value, when):
        self.hass.states.async_set(entity, value, timestamp=when)
        await async_wait_recording_done(self.hass)

    async def game(self, value, when):
        await self.state(self.source, value, when)

    async def retained(self, value, when):
        """A new HA run re-creates the state (fresh state machine) at ``when``."""
        self.hass.states.async_remove(self.source)
        await self.game(value, when)

    async def restart(self, when, retained):
        """New HA run: fresh state machine, ``unknown`` first, then the retained MQTT value."""
        self.hass.states.async_remove(self.source)
        self.hass.states.async_remove(self.uptime)
        await self.game("unknown", when)
        await self.game(retained, when + 1)

    def coordinator(self):
        coordinator = GamingCoordinator(self.hass, self.entry)
        self.created.append(coordinator)
        return coordinator

    async def totals(self, now, coordinator=None):
        self.freezer.move_to(now)
        coordinator = coordinator or self.coordinator()
        data = await coordinator._async_update_data()
        return data["totals"]


@pytest.fixture
async def rig(hass, freezer):
    await hass.config.async_set_time_zone("Europe/Zagreb")
    rig = Rig(hass, freezer)
    yield rig
    for coordinator in rig.created:  # cancel the refresh debouncer left by live events
        coordinator.close()
        await coordinator.async_shutdown()


def assert_totals(totals, daily=0, weekly=0, weekend=0, roblox=0, minecraft=0):
    assert totals["daily"] == daily
    assert totals["weekly"] == weekly
    assert totals["weekend_total"] == weekend
    assert totals["per_game"]["Roblox"] == roblox
    assert totals["per_game"]["Minecraft"] == minecraft


NOW = at(11, 16, 12)  # Monday 2026-11-16 12:00 Europe/Zagreb
RUNTIME_PKG = Path(__file__).resolve().parents[2] / "custom_components" / "smarthouse_gaming"


@pytest.mark.parametrize("value", [None, "unknown", "unavailable"])
async def test_cold_startup_counts_nothing(rig, value):
    """Empty Recorder / absent, unknown or unavailable source and no heartbeats: 0."""
    if value is not None:
        await rig.game(value, ts(11, 16, 11, 59))
        await rig.state(rig.in_game, "unavailable", ts(11, 16, 11, 59))
    assert_totals(await rig.totals(NOW))


async def test_retained_game_without_any_heartbeat_counts_nothing(rig):
    await rig.game("Roblox", ts(11, 16, 11, 59))
    await rig.state(rig.uptime, str(UPTIME0), ts(11, 16, 11, 59))  # a single beat is no interval
    assert_totals(await rig.totals(NOW))


async def test_graceful_shutdown_gap_not_counted(rig):
    await rig.game("Roblox", ts(11, 16, 7))
    await rig.beats(ts(11, 16, 6), ts(11, 16, 8))  # HA stops at 08:00, restarts at 11:00
    await rig.restart(ts(11, 16, 11), "idle")
    await rig.beats(ts(11, 16, 11), ts(11, 16, 12))
    # Only 07:00-08:00 was observed; 08:00-11:00 is unknown, not Roblox.
    assert_totals(await rig.totals(NOW), daily=H, weekly=H, roblox=H)


async def test_gap_then_game_still_running_counts_only_observed(rig):
    await rig.game("Roblox", ts(11, 16, 7))
    await rig.beats(ts(11, 16, 6), ts(11, 16, 8))
    await rig.restart(ts(11, 16, 11), "Roblox")  # retained value re-observed after restart
    await rig.beats(ts(11, 16, 11), ts(11, 16, 12))
    assert_totals(await rig.totals(NOW), daily=2 * H - 1, weekly=2 * H - 1, roblox=2 * H - 1)


async def test_crash_gap_keeps_observed_play_before_last_row(rig):
    """Unclean stop: no end is recorded; the last observed heartbeat bounds the observed play."""
    await rig.game("Roblox", ts(11, 16, 7))
    await rig.game("idle", ts(11, 16, 7, 30))
    await rig.game("Minecraft", ts(11, 16, 8))  # last row before the crash
    await rig.beats(ts(11, 16, 6), ts(11, 16, 8))
    await rig.restart(ts(11, 16, 11), "idle")
    await rig.beats(ts(11, 16, 11), ts(11, 16, 12))
    assert_totals(await rig.totals(NOW), daily=30 * M, weekly=30 * M, roblox=30 * M)


async def test_unavailable_and_recovery_count_only_observed_play(rig):
    await rig.game("Roblox", ts(11, 16, 7))
    await rig.game("unavailable", ts(11, 16, 8))
    await rig.state(rig.in_game, "unavailable", ts(11, 16, 8))
    await rig.game("unknown", ts(11, 16, 9))
    await rig.game("Roblox", ts(11, 16, 10))
    await rig.game("idle", ts(11, 16, 10, 30))
    await rig.beats(ts(11, 16, 6), ts(11, 16, 12))
    assert_totals(await rig.totals(NOW), daily=H + 30 * M, weekly=H + 30 * M, roblox=H + 30 * M)


async def test_currently_unavailable_snapshot_counts_nothing_after_last_row(rig):
    await rig.game("Roblox", ts(11, 16, 7))
    await rig.game("unavailable", ts(11, 16, 7, 30))
    await rig.state(rig.in_game, "unavailable", ts(11, 16, 7, 30))
    await rig.beats(ts(11, 16, 6), ts(11, 16, 12))
    assert_totals(await rig.totals(NOW), daily=30 * M, weekly=30 * M, roblox=30 * M)


async def test_restart_reads_history_plus_live_snapshot_without_double_counting(rig):
    await rig.game("idle", ts(11, 16, 6, 30))
    await rig.beats(ts(11, 16, 6), ts(11, 16, 9))
    first = rig.coordinator()
    await rig.totals(at(11, 16, 9), first)  # subscribes to live events
    rig.freezer.move_to(at(11, 16, 10))
    await rig.beats(ts(11, 16, 9, 1), ts(11, 16, 11))  # live heartbeats, also committed
    await rig.game("Roblox", ts(11, 16, 10))  # live event AND committed Recorder row
    live = await rig.totals(at(11, 16, 11), first)
    assert_totals(live, daily=H, weekly=H, roblox=H)
    # HA restarts: a brand-new coordinator reads Recorder history plus the live snapshot.
    restarted = await rig.totals(at(11, 16, 11), rig.coordinator())
    assert restarted == live
    # Refreshing the same coordinator again must not add the pending event twice.
    again = await rig.totals(at(11, 16, 11), first)
    assert again == live


async def test_stale_pre_restart_state_is_not_extrapolated_to_restart(rig):
    await rig.game("Roblox", ts(11, 16, 10))
    await rig.beats(ts(11, 16, 9), ts(11, 16, 10, 30))
    # Retained MQTT value delivered by the new run; stamped when HA saw it, not 10:00.
    await rig.restart(ts(11, 16, 11), "Roblox")
    await rig.beats(ts(11, 16, 11), ts(11, 16, 12))
    observed = 30 * M + H - 1  # retained value arrives 1 s after the fresh ``unknown`` row
    assert_totals(await rig.totals(NOW), daily=observed, weekly=observed, roblox=observed)


async def test_gap_spanning_week_boundary_does_not_leak_into_new_week(rig):
    await rig.game("Roblox", ts(11, 15, 21))
    await rig.beats(ts(11, 15, 20), ts(11, 15, 22))
    await rig.restart(ts(11, 16, 2), "Roblox")
    await rig.beats(ts(11, 16, 2), ts(11, 16, 3))
    # Monday 03:00: only 02:00-03:00 is observed in the new week; Sunday 21:00 state is stale.
    assert_totals(await rig.totals(at(11, 16, 3)), daily=H - 1, weekly=H - 1, roblox=H - 1)


async def test_gap_spanning_week_boundary_with_idle_after_counts_zero(rig):
    await rig.game("Roblox", ts(11, 15, 21))
    await rig.beats(ts(11, 15, 20), ts(11, 15, 22))
    await rig.restart(ts(11, 16, 2), "idle")
    await rig.beats(ts(11, 16, 2), ts(11, 16, 3))
    assert_totals(await rig.totals(at(11, 16, 3)))


async def test_weekend_gap_across_midnight_counts_only_observed(rig):
    await rig.game("Roblox", ts(11, 21, 20))
    await rig.beats(ts(11, 21, 19), ts(11, 21, 22))
    await rig.restart(ts(11, 22, 9), "idle")
    await rig.beats(ts(11, 22, 9), ts(11, 22, 12))
    assert_totals(await rig.totals(at(11, 22, 12)), daily=0, weekly=2 * H, weekend=2 * H,
                  roblox=0)


async def test_dst_fall_back_day_counts_25_hour_day_by_real_elapsed_time(rig):
    await rig.beats(ts(10, 24, 23), ts(10, 25, 12))
    await rig.game("Roblox", ts(10, 25, 2, 30, fold=0))
    await rig.game("idle", ts(10, 25, 2, 30, fold=1))
    assert_totals(await rig.totals(at(10, 25, 12)), daily=H, weekly=H, weekend=H, roblox=H)


async def test_dst_fall_back_gap_counts_only_observed_real_time(rig):
    await rig.game("Roblox", ts(10, 25, 1))
    await rig.beats(ts(10, 24, 23), ts(10, 25, 1, 30))
    await rig.restart(ts(10, 25, 4), "idle")
    await rig.beats(ts(10, 25, 4), ts(10, 25, 12))
    assert_totals(await rig.totals(at(10, 25, 12)), daily=30 * M, weekly=30 * M,
                  weekend=30 * M, roblox=30 * M)


async def test_recorder_lag_live_event_not_yet_committed_is_counted_once(rig):
    await rig.game("idle", ts(11, 16, 6, 30))
    await rig.beats(ts(11, 16, 6), ts(11, 16, 9))
    coordinator = rig.coordinator()
    await rig.totals(at(11, 16, 9), coordinator)
    await async_block_recorder(rig.hass, 1)  # recorder thread cannot commit meanwhile
    rig.freezer.move_to(at(11, 16, 10))
    await rig.beats(ts(11, 16, 9, 1), ts(11, 16, 11), wait=False)  # live heartbeats only
    rig.hass.states.async_set(rig.source, "Roblox", timestamp=ts(11, 16, 10))
    await rig.hass.async_block_till_done()
    lagging = await rig.totals(at(11, 16, 11), coordinator)
    assert_totals(lagging, daily=H, weekly=H, roblox=H)
    await async_wait_recording_done(rig.hass)
    committed = await rig.totals(at(11, 16, 11), coordinator)
    assert committed == lagging


async def test_live_transition_wins_over_recorder_row_at_equal_timestamp(rig):
    await rig.game("Roblox", ts(11, 16, 10))
    await rig.beats(ts(11, 16, 6), ts(11, 16, 12))
    coordinator = rig.coordinator()
    coordinator.source = rig.source  # live event seen before the first history load
    coordinator.uptime_source = rig.uptime
    coordinator.transitions = [(ts(11, 16, 10), "idle")]
    assert_totals(await rig.totals(at(11, 16, 11), coordinator), daily=0, weekly=0)


@pytest.mark.parametrize("outage, counted", [(90, 90), (91, 0)])
async def test_outage_at_the_heartbeat_tolerance_boundary(rig, outage, counted):
    """The 90 s tolerance of PR #8 is the documented limit: shorter outages are
    indistinguishable from MQTT jitter and keep the game state, longer ones are unobserved."""
    await rig.game("Roblox", ts(11, 16, 7))
    await rig.beats(ts(11, 16, 7), ts(11, 16, 8))
    await rig.beats(ts(11, 16, 8) + outage, ts(11, 16, 8) + outage + M)
    # 07:00-08:00 and the final observed minute count; the outage only within tolerance.
    expected = H + counted + M
    assert_totals(await rig.totals(at(11, 16, 9)), daily=expected, weekly=expected,
                  roblox=expected)


def test_single_mechanism_no_recorder_runs_reconciliation():
    """Recorder downtime is handled only by coverage.py; no second masking layer."""
    assert not (RUNTIME_PKG / "downtime.py").exists()
    assert "RecorderRuns" not in (RUNTIME_PKG / "coordinator.py").read_text()


async def test_coordinator_missing_source_resets_enforcement(rig):
    c = rig.coordinator()
    c.last_signature = ("previous",)
    with patch.object(c, "entity_id", return_value=None), patch.object(c.liveness, "reset") as reset:
        assert await c._async_update_data() == {"ready": False, "online": False}
    reset.assert_called_once()
    assert c.last_signature is None


async def test_coordinator_recorder_failure_is_reported_without_actions(rig):
    c = rig.coordinator()
    failure = OSError("synthetic recorder failure")
    with patch.object(c, "_prepare_source", new_callable=AsyncMock, side_effect=failure), \
            patch("custom_components.smarthouse_gaming.coordinator.mqtt.async_publish", new_callable=AsyncMock) as publish:
        with pytest.raises(UpdateFailed, match="Cannot load Recorder history") as error:
            await c._async_update_data()
    assert error.value.__cause__ is failure
    publish.assert_not_awaited()


async def prepare_restricted_coordinator(rig, in_game="on"):
    rig.freezer.move_to(NOW)
    rig.hass.config_entries.async_update_entry(
        rig.entry, options={"enabled": True, "daily": 0, "actions": ["terminate_game", "lock_pc"]})
    await rig.game("Roblox", NOW.timestamp())
    await rig.state(rig.in_game, in_game, NOW.timestamp())
    await rig.state(rig.uptime, "100", NOW.timestamp())
    return rig.coordinator()


async def test_coordinator_never_enforces_inconsistent_telemetry(rig):
    c = await prepare_restricted_coordinator(rig, in_game="off")
    c.last_signature = ("previous",)
    with patch.object(c.liveness, "observe", return_value=True), \
            patch("custom_components.smarthouse_gaming.coordinator.mqtt.async_publish", new_callable=AsyncMock) as publish:
        data = await c._async_update_data()
    assert data["ready"] and not data["online"]
    assert data["active"] == ["Roblox"]
    assert "daily" in data["reasons"]
    assert c.last_signature is None
    publish.assert_not_awaited()


async def test_coordinator_action_retry_boundary(rig):
    c = await prepare_restricted_coordinator(rig)
    from custom_components.smarthouse_gaming.const import RETRY_SECONDS
    with patch.object(c.liveness, "observe", return_value=True), \
            patch("custom_components.smarthouse_gaming.coordinator.monotonic", return_value=100) as clock, \
            patch("custom_components.smarthouse_gaming.coordinator.mqtt.async_publish", new_callable=AsyncMock) as publish:
        data = await c._async_update_data()
        assert data["online"] and data["reasons"] == ["daily"]
        assert [call.args[1] for call in publish.await_args_list] == [
            "SmartHouse/Gaming/pc1/command/terminate_game",
            "SmartHouse/Gaming/pc1/command/lock_pc"]
        assert all(call.args[2] == "PRESS" and call.kwargs == {"qos": 0, "retain": False}
                   for call in publish.await_args_list)
        clock.return_value = 100 + RETRY_SECONDS - 0.01
        await c._async_update_data()
        assert publish.await_count == 2
        clock.return_value = 100 + RETRY_SECONDS
        await c._async_update_data()
        assert publish.await_count == 4


@pytest.mark.parametrize("change", [{"unlimited": True}, {"actions": ["terminate_game"]}])
async def test_coordinator_rechecks_live_settings_between_actions(rig, change):
    c = await prepare_restricted_coordinator(rig)

    async def change_options(*args, **kwargs):
        rig.hass.config_entries.async_update_entry(rig.entry, options=dict(rig.entry.options) | change)

    with patch.object(c.liveness, "observe", return_value=True), \
            patch("custom_components.smarthouse_gaming.coordinator.mqtt.async_publish", new_callable=AsyncMock,
                  side_effect=change_options) as publish:
        await c._async_update_data()
    publish.assert_awaited_once_with(rig.hass, "SmartHouse/Gaming/pc1/command/terminate_game",
                                     "PRESS", qos=0, retain=False)
    assert c.last_signature is None


async def test_coordinator_action_failure_does_not_skip_next_action(rig):
    c = await prepare_restricted_coordinator(rig)
    with patch.object(c.liveness, "observe", return_value=True), \
            patch("custom_components.smarthouse_gaming.coordinator.mqtt.async_publish", new_callable=AsyncMock,
                  side_effect=[OSError("synthetic publish failure"), None]) as publish:
        data = await c._async_update_data()
    assert data["online"]
    assert [call.args[1] for call in publish.await_args_list] == [
        "SmartHouse/Gaming/pc1/command/terminate_game",
        "SmartHouse/Gaming/pc1/command/lock_pc"]


async def test_registry_domain_transfer_preserves_recorded_entity_history(rig):
    """A registry-only identity transfer must not rewrite historical Recorder state IDs."""
    from homeassistant.components.recorder import get_instance

    registry = er.async_get(rig.hass)
    scoped = registry.async_get_or_create(
        "sensor", DOMAIN, "pc1_current_game", config_entry=rig.entry,
        suggested_object_id="pc1_scoped_current_game")
    replacement = MockConfigEntry(domain="parental", unique_id="pc1", data=DATA)
    replacement.add_to_hass(rig.hass)

    rig.freezer.move_to(NOW)
    await rig.state(scoped.entity_id, "Roblox", ts(11, 16, 11, 58))
    await rig.state(scoped.entity_id, "idle", ts(11, 16, 11, 59))
    start = at(11, 16, 11, 57)
    coordinator = rig.coordinator()
    recorder = get_instance(rig.hass)

    async def read():
        return await recorder.async_add_executor_job(
            coordinator._read_history, scoped.entity_id, start, NOW)

    before = await read()
    assert (ts(11, 16, 11, 58), "Roblox") in before
    assert (ts(11, 16, 11, 59), "idle") in before

    # State machine rows are synthetic; there is no loaded Entity instance.
    registry.async_update_entity_platform(scoped.entity_id, "parental",
                                          new_config_entry_id=replacement.entry_id)
    await async_wait_recording_done(rig.hass)
    moved = registry.async_get(scoped.entity_id)
    assert moved.id == scoped.id and moved.entity_id == scoped.entity_id
    assert moved.config_entry_id == replacement.entry_id
    after = await read()
    assert after == before

    registry.async_update_entity_platform(scoped.entity_id, DOMAIN,
                                          new_config_entry_id=rig.entry.entry_id)
    await async_wait_recording_done(rig.hass)
    assert await read() == before
