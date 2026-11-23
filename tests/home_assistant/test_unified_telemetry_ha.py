"""End-to-end HA Unified Telemetry v3: single authoritative subscriber."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.components import mqtt

from custom_components.hal_gaming_control import foreground_source as src
from custom_components.hal_gaming_control import direct_mqtt
from custom_components.hal_gaming_control.foreground_source import ForegroundSource
from custom_components.hal_gaming_control.direct_mqtt import DirectUptime

pytestmark = pytest.mark.asyncio
APP = {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}
DEVICE_EPOCH = "a" * 32
DISPLAY_EPOCH = "b" * 32


def v3(device="pc1", ts=100, seq=1, *, epoch=DEVICE_EPOCH,
       fg="foreground", screen="on", event=1, event_age=100,
       fg_age=0, display_age=0):
    return json.dumps({
        "version": 3, "device_id": device, "epoch": epoch,
        "sequence": seq, "observed_at": ts,
        "foreground": {
            "state": fg, "process": APP["process"] if fg == "foreground" else None,
            "signature": None, "sample_age_ms": fg_age},
        "display": {
            "state": screen, "scope": "windows_console",
            "event_epoch": DISPLAY_EPOCH if screen != "unknown" else None,
            "event_sequence": event if screen != "unknown" else None,
            "event_age_ms": event_age if screen != "unknown" else None,
            "sample_age_ms": display_age, "ac_timeout_seconds": 600,
            "dc_timeout_seconds": 300, "power_source": "ac",
            "last_input_idle_ms": 600000},
        "system": {
            "uptime_seconds": 100000 + ts, "agent_version": "0.2.12",
            "agent_build_sha": None},
    })


async def start(hass, device="pc1", *, screen=True):
    callbacks, unsubscribed = {}, []
    async def subscribe(_hass, topic, callback, qos):
        callbacks[topic] = (callback, qos)
        return lambda: unsubscribed.append(topic)

    changed, bonuses = Mock(), Mock()
    with patch.object(mqtt, "is_connected", return_value=True), \
         patch.object(mqtt, "async_subscribe_connection_status",
                      return_value=lambda: unsubscribed.append("connection")), \
         patch.object(mqtt, "async_subscribe", side_effect=subscribe):
        watcher = ForegroundSource(hass, device, [APP], changed,
                                   screen_enabled=screen, on_screen_off=bonuses,
                                   unified_enabled=True)
        await watcher.async_start()
    # The matching Windows publisher advertises this capability on a
    # retained discovery topic; the parent toggle alone is insufficient.
    watcher._v3_discovery(SimpleNamespace(
        topic=f"SmartHouse/Gaming/{device}/discovery",
        payload=json.dumps({
            "protocol_version": 1, "device_id": device, "name": "Gaming PC",
            "games": [], "actions": [], "unified_telemetry_protocol": 3})))
    assert watcher.v3_capable
    return watcher, callbacks, changed, bonuses, unsubscribed


def deliver(callbacks, topic, payload, *, ts, retained=False):
    cb = callbacks[topic][0]
    msg = SimpleNamespace(topic=topic, payload=payload, retain=retained)
    with patch.object(src, "time", return_value=ts), \
         patch.object(src, "monotonic", return_value=10000 + ts):
        cb(msg)


def total(source, ts=150):
    return source.totals(datetime.fromtimestamp(ts, timezone.utc))["weekly"]


async def test_v3_subscribes_single_read_only_source_and_ignores_legacy(hass):
    s, cb, changed, _, unsub = await start(hass, screen=True)
    root = "SmartHouse/Gaming/pc1"
    assert set(cb) == {
        root + "/availability", root + "/discovery", root + "/state/telemetry"}
    assert cb[root + "/state/telemetry"][1] == 0
    deliver(cb, root + "/availability", "online", ts=99)
    deliver(cb, root + "/state/telemetry", v3(ts=100, seq=1), ts=100)
    assert s.current(10100) is None  # First ON cannot carry old gameplay.
    deliver(cb, root + "/state/telemetry", v3(ts=102, seq=2), ts=102)
    assert s.current(10102) == "Roblox"
    deliver(cb, root + "/state/telemetry", v3(ts=104, seq=3), ts=104)
    assert total(s) == 2
    assert s.system_uptime == 100104
    assert s.display_details["ac_timeout_seconds"] == 600
    assert s.last_raw["process"] == APP["process"]
    assert changed.call_count >= 3
    s.close()
    assert len(unsub) == 4


async def test_off_and_repeated_raw_focus_never_fabricate_game_time_or_bonus(hass):
    s, cb, changed, bonus, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    deliver(cb, root + "/state/telemetry", v3(ts=100, seq=1), ts=100)
    deliver(cb, root + "/state/telemetry", v3(ts=102, seq=2), ts=102)
    deliver(cb, root + "/state/telemetry", v3(ts=104, seq=3), ts=104)
    base = total(s)
    assert base == 2
    # Transition display event processed before foreground of same packet.
    deliver(cb, root + "/state/telemetry",
            v3(ts=106, seq=4, screen="off", event=2), ts=106)
    assert s.current(10106) == "idle"
    assert s.last_raw is None
    assert bonus.call_count == 1
    for ts, seq in ((108, 5), (110, 6)):
        deliver(cb, root + "/state/telemetry",
                v3(ts=ts, seq=seq, screen="off", event=2, event_age=(ts-106)*1000),
                ts=ts)
    assert total(s) == base
    assert bonus.call_count == 1
    # ON must be followed by another *later* verified raw observation.
    deliver(cb, root + "/state/telemetry",
            v3(ts=112, seq=7, screen="on", event=3), ts=112)
    assert s.current(10112) is None
    deliver(cb, root + "/state/telemetry",
            v3(ts=114, seq=8, screen="on", event=3), ts=114)
    assert s.current(10114) == "Roblox"
    deliver(cb, root + "/state/telemetry",
            v3(ts=116, seq=9, screen="on", event=3), ts=116)
    assert total(s) == base + 2
    assert bonus.call_count == 1
    s.close()


async def test_legacy_v2_never_double_counts_when_v3_selected(hass):
    s, cb, _, _, _ = await start(hass, screen=False)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", b"online", ts=99)
    deliver(cb, root + "/state/telemetry", v3(ts=100, seq=1), ts=100)
    deliver(cb, root + "/state/telemetry", v3(ts=102, seq=2), ts=102)
    assert total(s) == 2
    assert root + "/state/foreground_identity" not in cb
    assert root + "/state/display_context" not in cb
    s.close()


async def test_replay_wrong_pc_stale_retained_and_reconnect_fail_closed(hass):
    s, cb, _, bonus, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    deliver(cb, root + "/state/telemetry", v3(ts=100, seq=1), ts=100)
    deliver(cb, root + "/state/telemetry", v3(ts=102, seq=2), ts=102)
    deliver(cb, root + "/state/telemetry", v3(ts=104, seq=3), ts=104)
    prev = total(s)
    deliver(cb, root + "/state/telemetry", v3(ts=102, seq=2), ts=105)
    assert total(s) == prev
    deliver(cb, root + "/state/telemetry", v3(ts=106, seq=4), ts=106, retained=True)
    assert s.current(10106) is None
    deliver(cb, root + "/state/telemetry", v3("pc2", ts=107, seq=5), ts=107)
    assert s.current(10107) is None
    assert bonus.call_count == 0
    deliver(cb, root + "/state/telemetry", v3(ts=110, seq=6), ts=110)
    assert s.current(10110) is None  # must re-arm after unknown display
    deliver(cb, root + "/state/telemetry", v3(ts=111, seq=7), ts=111)
    assert s.current(10111) == "Roblox"
    s._connection(False)
    assert s.current(10110) is None
    s._connection(True)
    deliver(cb, root + "/availability", "online", ts=111)
    s._v3_discovery(SimpleNamespace(
        topic=root + "/discovery",
        payload=json.dumps({"protocol_version": 1, "device_id": "pc1",
                            "name": "PC", "games": [], "actions": [],
                            "unified_telemetry_protocol": 3})))
    deliver(cb, root + "/state/telemetry", v3(ts=112, seq=8), ts=112)
    assert s.current(10112) is None  # old epoch retired
    deliver(cb, root + "/state/telemetry",
            v3(ts=114, seq=1, epoch="c" * 32), ts=114)
    # First new epoch can arm ON but must not immediately credit old focus.
    assert s.current(10114) is None
    deliver(cb, root + "/state/telemetry",
            v3(ts=116, seq=2, epoch="c" * 32), ts=116)
    assert s.current(10116) == "Roblox"
    assert bonus.call_count == 0
    s.close()


async def test_stale_display_and_foreground_are_unknown_not_confirmed_idle(hass):
    s, cb, _, _, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    deliver(cb, root + "/state/telemetry",
            v3(ts=100, seq=1), ts=100)
    deliver(cb, root + "/state/telemetry",
            v3(ts=102, seq=2, fg_age=12000), ts=102)
    assert s.current(10102) is None
    assert s.last_raw is None
    assert s.system_uptime == 100102
    deliver(cb, root + "/state/telemetry",
            v3(ts=104, seq=3, screen="off", event=2, event_age=42000), ts=104)
    assert s.display.current(10104) == "unknown"
    assert s.current(10104) is None
    s.close()


async def test_two_devices_do_not_share_epoch_or_off_bonus(hass):
    one, a, _, bonusa, _ = await start(hass, "pc1")
    two, b, _, bonusb, _ = await start(hass, "pc2")
    for dev, callbacks in (("pc1", a), ("pc2", b)):
        root = f"SmartHouse/Gaming/{dev}"
        deliver(callbacks, root + "/availability", "online", ts=99)
        deliver(callbacks, root + "/state/telemetry", v3(dev, 100, 1), ts=100)
        deliver(callbacks, root + "/state/telemetry", v3(dev, 102, 2), ts=102)
    root1 = "SmartHouse/Gaming/pc1"
    deliver(a, root1 + "/state/telemetry",
            v3("pc1", 104, 3, screen="off", event=2), ts=104)
    assert one.current(10104) == "idle"
    assert two.current(10102) == "Roblox"
    assert bonusa.call_count == 1
    assert bonusb.call_count == 0
    one.close()
    two.close()


async def test_direct_uptime_preserves_unique_id_and_rejects_bad_v3(hass):
    c = Mock()
    c.device_id = "pc1"
    c.entry.options = {"unified_telemetry_enabled": True}
    c.entry.data = {"name": "PC"}
    c.foreground.v3_capable = True
    direct = DirectUptime(c)
    direct.async_write_ha_state = Mock()
    assert direct.unique_id == "pc1_uptime"
    assert direct._state_key is None
    direct._connected = direct._online = True
    topic = "SmartHouse/Gaming/pc1/state/telemetry"
    msg = lambda payload, retain=False: SimpleNamespace(
        topic=topic, payload=payload, retain=retain)
    with patch.object(direct_mqtt, "time", return_value=100), \
         patch.object(direct_mqtt, "monotonic", return_value=1000):
        direct._v3_telemetry(msg(v3(ts=100)))
        assert direct.native_value == 100100
        assert direct.available
    with patch.object(direct_mqtt, "time", return_value=102), \
         patch.object(direct_mqtt, "monotonic", return_value=1002):
        direct._v3_telemetry(msg(v3(ts=102, seq=2), True))
        assert direct.native_value is None
        assert not direct.available
    with patch.object(direct_mqtt, "time", return_value=104), \
         patch.object(direct_mqtt, "monotonic", return_value=1004):
        direct._v3_telemetry(msg(v3(ts=104, seq=3)))
        assert direct.native_value == 100104
    with patch.object(direct_mqtt, "monotonic", return_value=1020):
        assert not direct.available
    direct._connection(False)
    assert direct.native_value is None
    assert not direct.available


async def test_v2_default_has_identical_existing_subscription_and_identity(hass):
    callbacks = {}
    async def sub(_, topic, cb, qos):
        callbacks[topic] = cb
        return lambda: None
    with patch.object(mqtt, "is_connected", return_value=True), \
         patch.object(mqtt, "async_subscribe_connection_status",
                      return_value=lambda: None), \
         patch.object(mqtt, "async_subscribe", side_effect=sub):
        source = ForegroundSource(hass, "pc1", [APP], Mock(), screen_enabled=True)
        await source.async_start()
    root = "SmartHouse/Gaming/pc1"
    assert set(callbacks) == {
        root + "/availability", root + "/state/foreground_identity",
        root + "/state/display_context"}
    assert source.telemetry_order is None
    source.close()



@pytest.mark.usefixtures("recorder_mock")
async def test_options_explicit_v3_ack_preserves_budgets_and_screen_idle(
        hass, enable_custom_integrations):
    from homeassistant import data_entry_flow
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.hal_gaming_control.const import DOMAIN
    from custom_components.hal_gaming_control.coordinator import GamingCoordinator

    original = {"daily": 180, "weekly": 300, "tracked_apps": [APP],
                "screen_idle_enabled": False, "unified_telemetry_enabled": False}
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="pc1", title="PC",
        data={"device_id": "pc1", "name": "PC", "games": [],
              "actions": []}, options=original)
    entry.add_to_hass(hass)
    manager = hass.config_entries.options
    init = await manager.async_init(entry.entry_id)
    assert "unified_telemetry" in init["menu_options"]
    form = await manager.async_configure(
        init["flow_id"], {"next_step_id": "unified_telemetry"})
    assert form["type"] == data_entry_flow.FlowResultType.FORM
    refused = await manager.async_configure(
        init["flow_id"], {"unified_telemetry_enabled": True,
                          "unified_telemetry_acknowledged": False})
    assert refused["errors"]["base"] == "unified_telemetry_unconfirmed"
    assert entry.options == original
    confirmed = await manager.async_configure(
        init["flow_id"], {"unified_telemetry_enabled": True,
                          "unified_telemetry_acknowledged": True})
    assert confirmed["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert confirmed["data"]["unified_telemetry_enabled"] is True
    assert confirmed["data"]["tracked_apps"] == [APP]
    assert confirmed["data"]["daily"] == 180
    assert confirmed["data"]["screen_idle_enabled"] is False
    assert GamingCoordinator.policy_snapshot(confirmed["data"])[
        "unified_telemetry_enabled"] is True


@pytest.mark.usefixtures("recorder_mock")
async def test_coordinator_passes_v3_only_when_explicitly_enabled(hass):
    from unittest.mock import AsyncMock
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.hal_gaming_control import coordinator as co
    from custom_components.hal_gaming_control.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="pc1", title="PC",
        data={"device_id": "pc1", "name": "PC", "games": [], "actions": []},
        options={"tracked_apps": [APP], "unified_telemetry_enabled": True})
    entry.add_to_hass(hass)
    c = co.GamingCoordinator(hass, entry)
    store = Mock()
    store.async_load = AsyncMock(return_value=())
    store.async_save = AsyncMock()
    source = Mock()
    source.async_start = AsyncMock()
    source.export_segments.return_value = ()
    with patch.object(co, "async_activate_cutover", new=AsyncMock(return_value=100)), \
         patch.object(co, "ForegroundStore", return_value=store), \
         patch.object(co, "ForegroundSource", return_value=source) as new_source:
        await c.async_start_foreground()
    assert new_source.call_args.kwargs["unified_enabled"] is True
    assert new_source.call_args.kwargs["intervals"] == ()
    await c.async_stop_foreground()
    c.close()


async def test_existing_active_game_sensor_exposes_diagnostics_as_attributes():
    from custom_components.hal_gaming_control.sensor import ActiveGameSensor
    c = Mock()
    c.device_id = "pc1"
    c.entry.data = {"name": "PC"}
    c.data = {
        "unified_telemetry": True, "active_game": "Roblox",
        "uptime_seconds": 123456,
        "display_details": {
            "state": "on", "scope": "windows_console",
            "event_age_ms": 120, "ac_timeout_seconds": 600,
            "dc_timeout_seconds": 300, "power_source": "ac",
            "last_input_idle_ms": 123000},
    }
    entity = ActiveGameSensor(c)
    assert entity.unique_id == "pc1_active_game"
    assert entity.native_value == "Roblox"
    attrs = entity.extra_state_attributes
    assert attrs["display_ac_timeout_seconds"] == 600
    assert attrs["display_dc_timeout_seconds"] == 300
    assert attrs["last_input_idle_ms"] == 123000
    assert attrs["system_uptime_seconds"] == 123456
    assert "username" not in attrs and "process" not in attrs



async def test_v3_requires_verified_discovery_not_just_parent_toggle(hass):
    s, cb, _, _, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    s._v3_discovery(SimpleNamespace(
        topic=root + "/discovery",
        payload=json.dumps({"protocol_version": 1, "device_id": "pc1",
                            "name": "PC", "games": [], "actions": [],
                            "unified_telemetry_protocol": 1})))
    assert s.v3_capable is False
    deliver(cb, root + "/state/telemetry", v3(ts=100), ts=100)
    assert s.current(10100) is None
    assert total(s) == 0
    s._v3_discovery(SimpleNamespace(
        topic=root + "/discovery",
        payload=json.dumps({"protocol_version": 1, "device_id": "pc1",
                            "name": "PC", "games": [], "actions": [],
                            "unified_telemetry_protocol": 3})))
    deliver(cb, root + "/state/telemetry", v3(ts=102, seq=2), ts=102)
    assert s.current(10102) is None
    deliver(cb, root + "/state/telemetry", v3(ts=104, seq=3), ts=104)
    assert s.current(10104) == "Roblox"
    s.close()


async def test_stale_cached_off_never_presents_confirmed_idle_forever(hass):
    s, cb, _, bonus, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    deliver(cb, root + "/state/telemetry",
            v3(ts=100, seq=1), ts=100)
    deliver(cb, root + "/state/telemetry",
            v3(ts=102, seq=2), ts=102)
    deliver(cb, root + "/state/telemetry",
            v3(ts=104, seq=3, screen="off", event=2), ts=104)
    assert s.current(10104) == "idle"
    assert s.current(10115) is None  # Lost MQTT stream, not ongoing proof.
    assert s.system_uptime is None
    assert s.display_details is None
    assert bonus.call_count == 1
    s.close()


async def test_post_on_requires_helper_sample_after_actual_console_edge(hass):
    """A newer MQTT envelope must not resurrect pre-ON foreground activity.

    The Windows publisher can report fresh event evidence and the last helper
    sample in the same snapshot; the latter may still predate console ON.
    """
    watcher, cb, _, bonus, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    for ts, sequence in ((100, 1), (102, 2), (104, 3)):
        deliver(cb, root + "/state/telemetry",
                v3(ts=ts, seq=sequence), ts=ts)
    previous = total(watcher)
    assert previous == 2
    deliver(cb, root + "/state/telemetry",
            v3(ts=106, seq=4, screen="off", event=2), ts=106)
    assert watcher.current(10106) == "idle"
    # First ON notification represents a console edge at wall clock 111.9 s.
    deliver(cb, root + "/state/telemetry",
            v3(ts=112, seq=5, screen="on", event=3,
               event_age=100, fg_age=200), ts=112)
    assert watcher.current(10112) is None
    # Later MQTT packet, still with pre-ON foreground helper sample (111.8s).
    # Must stay UNKNOWN, rather than charge time or authorize targeted actions.
    deliver(cb, root + "/state/telemetry",
            v3(ts=113, seq=6, screen="on", event=3,
               event_age=1100, fg_age=1200), ts=113)
    assert watcher.current(10113) is None
    assert watcher.last_raw is None
    assert total(watcher) == previous
    # A genuinely post-ON helper sample at 113.7 s arms foreground accounting.
    deliver(cb, root + "/state/telemetry",
            v3(ts=114, seq=7, screen="on", event=3,
               event_age=2100, fg_age=300), ts=114)
    assert watcher.current(10114) == "Roblox"
    assert total(watcher) == previous
    deliver(cb, root + "/state/telemetry",
            v3(ts=116, seq=8, screen="on", event=3,
               event_age=4100, fg_age=100), ts=116)
    assert total(watcher) > previous
    assert bonus.call_count == 1
    watcher.close()


async def test_offline_resets_post_on_freshness_watermark(hass):
    watcher, cb, _, _, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    deliver(cb, root + "/state/telemetry", v3(ts=100, seq=1), ts=100)
    assert watcher._needs_post_on
    deliver(cb, root + "/availability", "offline", ts=101)
    assert watcher._needs_post_on is False
    assert watcher._post_on_sequence is None
    assert watcher._post_on_timestamp is None
    watcher.close()


@pytest.mark.usefixtures("recorder_mock")
async def test_v3_only_hostname_recovers_every_parent_facing_sensor(hass):
    """#201: exercise MQTT -> foreground -> coordinator -> actual HA entities.

    A live Windows 0.4.0 v3-only publisher must restore the entire Sensors
    section once the per-PC v3 option and the new hostname identity match.
    """
    from unittest.mock import AsyncMock
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.hal_gaming_control import coordinator as co
    from custom_components.hal_gaming_control.binary_sensor import GamingRestriction
    from custom_components.hal_gaming_control.const import DOMAIN
    from custom_components.hal_gaming_control.sensor import (
        ActiveGameSensor, BudgetSensor, GamingTimeDisplaySensor,
    )

    host = "DESKTOP-LUCIJA"
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=host, title="Lucija Desktop",
        data={"device_id": host, "name": "Lucija Desktop",
              "games": [], "actions": []},
        options={"unified_telemetry_enabled": True,
                 "tracked_apps": [APP], "daily": 320, "weekly": 4200},
    )
    entry.add_to_hass(hass)
    coordinator = co.GamingCoordinator(hass, entry)
    watcher, callbacks, _, _, _ = await start(hass, host, screen=True)
    coordinator.foreground = watcher
    coordinator.storage_healthy = True
    coordinator.cutover_since = datetime.fromtimestamp(95, timezone.utc)
    coordinator.foreground_store = Mock()
    coordinator.foreground_store.async_save = AsyncMock()
    watcher.on_update = coordinator._live_foreground_changed
    entities = {
        "active": ActiveGameSensor(coordinator),
        "daily_budget": BudgetSensor(coordinator, "daily", "Daily budget remaining"),
        "weekly_budget": BudgetSensor(coordinator, "weekly", "Weekly budget remaining"),
        "daily_time": GamingTimeDisplaySensor(
            coordinator, "daily", "Daily gaming time"),
        "weekly_time": GamingTimeDisplaySensor(
            coordinator, "weekly", "Weekly gaming time"),
        "restriction": GamingRestriction(coordinator),
    }
    root = f"SmartHouse/Gaming/{host}"
    assert root + "/state/telemetry" in callbacks
    assert root + "/state/foreground_identity" not in callbacks
    assert all(entity.unique_id.startswith(host + "_") for entity in entities.values())

    # Availability/discovery by themselves cannot manufacture a live sensor.
    with patch.object(co, "monotonic", return_value=10099):
        deliver(callbacks, root + "/availability", "online", ts=99)
    assert all(not entity.available for entity in entities.values())

    # A complete, fresh v3 telemetry stream is sufficient; no v2 messages.
    for ts, seq in ((100, 1), (102, 2), (104, 3)):
        with patch.object(co, "monotonic", return_value=10000 + ts):
            deliver(callbacks, root + "/state/telemetry",
                    v3(host, ts=ts, seq=seq), ts=ts)

    assert coordinator.data["ready"] is True
    assert all(entity.available for entity in entities.values())
    assert entities["active"].native_value == "Roblox"
    assert entities["daily_budget"].native_value is not None
    assert entities["weekly_budget"].native_value is not None
    assert entities["daily_time"].native_value is not None
    assert entities["weekly_time"].native_value is not None
    assert entities["restriction"].is_on is False
    await hass.async_block_till_done()
    await coordinator.async_stop_foreground()
    coordinator.close()


@pytest.mark.usefixtures("recorder_mock")
async def test_old_mqtt_identity_cannot_make_new_hostname_sensors_look_live(hass):
    """#201: the old desktop_lucija entry must not consume a new hostname."""
    from unittest.mock import AsyncMock
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.hal_gaming_control import coordinator as co
    from custom_components.hal_gaming_control.const import DOMAIN
    from custom_components.hal_gaming_control.sensor import (
        ActiveGameSensor, BudgetSensor, GamingTimeDisplaySensor,
    )
    from custom_components.hal_gaming_control.binary_sensor import GamingRestriction

    old, host = "desktop_lucija", "DESKTOP-LUCIJA"
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=old, title="Lucija Desktop",
        data={"device_id": old, "name": "Lucija Desktop",
              "games": [], "actions": []},
        options={"unified_telemetry_enabled": True,
                 "tracked_apps": [APP], "daily": 320, "weekly": 4200},
    )
    entry.add_to_hass(hass)
    coordinator = co.GamingCoordinator(hass, entry)
    watcher, callbacks, _, _, _ = await start(hass, old, screen=False)
    coordinator.foreground = watcher
    coordinator.storage_healthy = True
    coordinator.cutover_since = datetime.fromtimestamp(95, timezone.utc)
    coordinator.foreground_store = Mock()
    coordinator.foreground_store.async_save = AsyncMock()
    watcher.on_update = coordinator._live_foreground_changed
    old_root = f"SmartHouse/Gaming/{old}"
    new_root = f"SmartHouse/Gaming/{host}"
    assert old_root + "/state/telemetry" in callbacks
    assert new_root + "/state/telemetry" not in callbacks

    with patch.object(co, "monotonic", return_value=10100):
        deliver(callbacks, old_root + "/availability", "online", ts=99)
        # A cross-device payload cannot make the legacy subscription live.
        deliver(callbacks, old_root + "/state/telemetry",
                v3(host, ts=100, seq=1), ts=100)
    sensors = [
        ActiveGameSensor(coordinator),
        BudgetSensor(coordinator, "daily", "Daily budget remaining"),
        BudgetSensor(coordinator, "weekly", "Weekly budget remaining"),
        GamingTimeDisplaySensor(coordinator, "daily", "Daily gaming time"),
        GamingTimeDisplaySensor(coordinator, "weekly", "Weekly gaming time"),
        GamingRestriction(coordinator),
    ]
    assert coordinator.data["ready"] is False
    assert all(not sensor.available for sensor in sensors)
    assert sensors[0].native_value is None
    await hass.async_block_till_done()
    await coordinator.async_stop_foreground()
    coordinator.close()
