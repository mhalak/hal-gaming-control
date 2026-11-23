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


async def start(hass, device="pc1"):
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
                                   on_screen_off=bonuses)
        await watcher.async_start()
    # The matching Windows publisher advertises this capability on a
    # retained discovery topic; screen handling has no parent toggle.
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
    s, cb, changed, _, unsub = await start(hass)
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
    assert s.observed_game == "Roblox"  # UI still shows fresh foreground.
    assert s.last_raw is None  # Accounting remains gated OFF.
    assert bonus.call_count == 1
    for ts, seq in ((108, 5), (110, 6)):
        deliver(cb, root + "/state/telemetry",
                v3(ts=ts, seq=seq, screen="off", event=2, event_age=(ts-106)*1000),
                ts=ts)
    assert total(s) == base
    assert s.observed_game == "Roblox"
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


async def test_off_foreground_is_observed_only_if_validated_and_fresh(hass):
    """Never keep the last game indefinitely when raw foreground changes."""
    watcher, cb, _, _, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    deliver(cb, root + "/state/telemetry",
            v3(ts=100, seq=1, screen="off", event=1), ts=100)
    assert watcher.current(10100) == "idle"
    assert watcher.observed_game == "Roblox"
    assert total(watcher) == 0

    deliver(cb, root + "/state/telemetry",
            v3(ts=102, seq=2, screen="off", event=1, fg="idle"), ts=102)
    assert watcher.observed_game == "idle"
    deliver(cb, root + "/state/telemetry",
            v3(ts=104, seq=3, screen="off", event=1, fg="unknown"), ts=104)
    assert watcher.observed_game is None
    assert watcher.current(10104) == "idle"
    assert total(watcher) == 0

    # Replayed out-of-order foreground cannot reintroduce a vanished game.
    deliver(cb, root + "/state/telemetry",
            v3(ts=102, seq=2, screen="off", event=1), ts=105)
    assert watcher.observed_game is None
    deliver(cb, root + "/availability", "offline", ts=106)
    assert watcher.observed_game is None
    watcher.close()


async def test_legacy_v2_never_double_counts_when_v3_selected(hass):
    s, cb, _, _, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", b"online", ts=99)
    deliver(cb, root + "/state/telemetry", v3(ts=100, seq=1), ts=100)
    deliver(cb, root + "/state/telemetry", v3(ts=102, seq=2), ts=102)
    deliver(cb, root + "/state/telemetry", v3(ts=104, seq=3), ts=104)
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
            v3(ts=104, seq=3, screen="off", event=2,
               event_age=100, display_age=9000), ts=104)
    assert s.display.current(10104) == "unknown"
    assert s.current(10104) == "Roblox"  # Stale OFF is not verified; gameplay still counts.
    s.close()


async def test_fresh_off_with_rejected_event_receipt_never_charges_game(hass):
    """An invalid OFF receipt is NOT an unsupported display-only PC.

    Incoming OFF must not appear as a verified OFF attribute, and must never
    allow continuing gaming accrual while awaiting a genuinely new ON edge.
    """
    s, cb, _, bonus, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=99)
    for ts, seq in ((100, 1), (102, 2), (104, 3)):
        deliver(cb, root + "/state/telemetry",
                v3(ts=ts, seq=seq, event=5), ts=ts)
    before_off = total(s)
    assert before_off == 2
    assert s.current(10104) == "Roblox"

    # Fresh validated v3 OFF, but the Windows display receipt regresses from
    # event sequence 5 to 4. The DisplayGate rejects it.
    deliver(cb, root + "/state/telemetry",
            v3(ts=106, seq=4, screen="off", event=4), ts=106)
    assert s.display.current(10106) == "unknown"
    assert s.display_details["state"] == "unknown"
    assert s.display_details["reported_state"] == "off"
    assert s.current(10106) is None
    assert total(s) == before_off
    assert bonus.call_count == 0

    # Repeated rejected OFF receipts must never restart gaming charging.
    deliver(cb, root + "/state/telemetry",
            v3(ts=108, seq=5, screen="off", event=4), ts=108)
    deliver(cb, root + "/state/telemetry",
            v3(ts=110, seq=6, screen="off", event=4), ts=110)
    assert s.current(10110) is None
    assert total(s) == before_off
    assert bonus.call_count == 0

    # A new verified ON and then a subsequent fresh foreground are required.
    deliver(cb, root + "/state/telemetry",
            v3(ts=112, seq=7, screen="on", event=6), ts=112)
    assert s.current(10112) is None
    assert total(s) == before_off
    deliver(cb, root + "/state/telemetry",
            v3(ts=114, seq=8, screen="on", event=6), ts=114)
    assert s.current(10114) == "Roblox"
    assert total(s) == before_off
    deliver(cb, root + "/state/telemetry",
            v3(ts=116, seq=9, screen="on", event=6), ts=116)
    assert total(s) > before_off
    s.close()


async def test_fresh_old_off_observations_from_real_pc_never_charge_after_cold_start(hass):
    """#212: 3h39m-old OFF edge with 156 ms samples is CURRENT OFF.

    Matches the owner's Windows v3 packet: Roblox foreground, monitor OFF,
    event_age_ms=13142547, display and foreground sample_age_ms=156.
    """
    s, cb, _, bonus, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=19999)
    for ts, seq, age in (
            (20000, 1, 13142547),
            (20002, 2, 13144547),
            (20004, 3, 13146547)):
        deliver(cb, root + "/state/telemetry",
                v3(ts=ts, seq=seq, screen="off", event=12,
                   event_age=age, fg_age=156, display_age=156), ts=ts)
        assert s.current(10000 + ts) == "idle"
        assert s.observed_game == "Roblox"
        assert s.display_details["state"] == "off"
    assert total(s, ts=20004) == 0
    bonus.assert_not_called()  # Booting into OFF is NOT a new OFF bonus edge.

    # Post-ON foreground freshness gate still prevents a premature charge.
    deliver(cb, root + "/state/telemetry",
            v3(ts=20006, seq=4, screen="on", event=13,
               event_age=100, fg_age=156, display_age=156), ts=20006)
    assert s.current(30006) is None
    assert total(s, ts=20006) == 0
    deliver(cb, root + "/state/telemetry",
            v3(ts=20008, seq=5, screen="on", event=13,
               event_age=2100, fg_age=156, display_age=156), ts=20008)
    assert s.current(30008) == "Roblox"
    assert total(s, ts=20008) == 0
    deliver(cb, root + "/state/telemetry",
            v3(ts=20010, seq=6, screen="on", event=13,
               event_age=4100, fg_age=156, display_age=156), ts=20010)
    assert total(s, ts=20010) > 0
    s.close()


async def test_off_stays_off_across_36s_and_hours_without_new_billing(hass):
    """#212: repeated fresh OFF samples, not recent state-change events."""
    s, cb, _, bonus, _ = await start(hass)
    root = "SmartHouse/Gaming/pc1"
    deliver(cb, root + "/availability", "online", ts=19999)
    for ts, seq, age in ((20000, 1, 100), (20002, 2, 2100),
                         (20004, 3, 4100)):
        deliver(cb, root + "/state/telemetry",
                v3(ts=ts, seq=seq, screen="on", event=11,
                   event_age=age), ts=ts)
    before_off = total(s, ts=20004)
    assert before_off > 0

    for ts, seq, age in ((20006, 4, 0), (20008, 5, 2000),
                         (20044, 6, 38000), (33148, 7, 13142000),
                         (33150, 8, 13144000)):
        deliver(cb, root + "/state/telemetry",
                v3(ts=ts, seq=seq, screen="off", event=12,
                   event_age=age, fg_age=156, display_age=156), ts=ts)
        assert s.current(10000 + ts) == "idle"
        assert s.observed_game == "Roblox"
        assert s.display_details["state"] == "off"
        assert total(s, ts=ts) == before_off
    assert bonus.call_count <= 1
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
    c.entry.options = {"unified_telemetry_enabled": False}
    c.entry.data = {"name": "PC"}
    c.foreground.v3_capable = True
    direct = DirectUptime(c)
    direct.async_write_ha_state = Mock()
    assert direct.unique_id == "pc1_uptime"
    assert direct.device_class is None
    assert direct.native_unit_of_measurement is None
    assert not hasattr(direct, "_state_key")
    direct._connected = direct._online = True
    topic = "SmartHouse/Gaming/pc1/state/telemetry"
    msg = lambda payload, retain=False: SimpleNamespace(
        topic=topic, payload=payload, retain=retain)
    with patch.object(direct_mqtt, "time", return_value=100), \
         patch.object(direct_mqtt, "monotonic", return_value=1000):
        direct._v3_telemetry(msg(v3(ts=100)))
        assert direct.native_value == "1d 3h 48m 20s"
        assert direct.extra_state_attributes["uptime_seconds"] == 100100
        assert direct.available
    with patch.object(direct_mqtt, "time", return_value=102), \
         patch.object(direct_mqtt, "monotonic", return_value=1002):
        direct._v3_telemetry(msg(v3(ts=102, seq=2), True))
        assert direct.native_value is None
        assert not direct.available
    with patch.object(direct_mqtt, "time", return_value=104), \
         patch.object(direct_mqtt, "monotonic", return_value=1004):
        direct._v3_telemetry(msg(v3(ts=104, seq=3)))
        assert direct.native_value == "1d 3h 48m 24s"
    with patch.object(direct_mqtt, "monotonic", return_value=1020):
        assert not direct.available
    direct._connection(False)
    assert direct.native_value is None
    assert not direct.available


async def test_default_source_is_unconditionally_v3_only(hass):
    """Without any per-PC toggle, HA subscribes to v3 only."""
    callbacks = {}
    async def sub(_, topic, cb, qos):
        callbacks[topic] = cb
        return lambda: None
    with patch.object(mqtt, "is_connected", return_value=True), \
         patch.object(mqtt, "async_subscribe_connection_status",
                      return_value=lambda: None), \
         patch.object(mqtt, "async_subscribe", side_effect=sub):
        source = ForegroundSource(hass, "pc1", [APP], Mock())
        await source.async_start()
    root = "SmartHouse/Gaming/pc1"
    assert set(callbacks) == {
        root + "/availability", root + "/discovery", root + "/state/telemetry"}
    assert root + "/state/foreground_identity" not in callbacks
    assert root + "/state/display_context" not in callbacks
    assert source.telemetry_order is not None
    source.close()



@pytest.mark.usefixtures("recorder_mock")
async def test_options_menu_has_no_telemetry_switch_and_keeps_existing_policy(
        hass, enable_custom_integrations):
    from homeassistant import data_entry_flow
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.hal_gaming_control.const import DOMAIN
    from custom_components.hal_gaming_control.coordinator import GamingCoordinator

    # A stale false option from the previous release must not disable v3.
    original = {"daily": 180, "weekly": 300, "tracked_apps": [APP],
                "screen_idle_enabled": False, "unified_telemetry_enabled": False}
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="pc1", title="PC",
        data={"device_id": "pc1", "name": "PC", "games": [],
              "actions": []}, options=original)
    entry.add_to_hass(hass)
    init = await hass.config_entries.options.async_init(entry.entry_id)
    assert init["type"] == data_entry_flow.FlowResultType.MENU
    assert "unified_telemetry" not in init["menu_options"]
    assert entry.options == original
    assert "unified_telemetry_enabled" not in GamingCoordinator.policy_snapshot(original)
    assert entry.options["tracked_apps"] == [APP]
    assert entry.options["daily"] == 180


@pytest.mark.usefixtures("recorder_mock")
async def test_coordinator_uses_v3_even_with_stale_disabled_option(hass):
    from unittest.mock import AsyncMock
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.hal_gaming_control import coordinator as co
    from custom_components.hal_gaming_control.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="pc1", title="PC",
        data={"device_id": "pc1", "name": "PC", "games": [], "actions": []},
        options={"tracked_apps": [APP], "unified_telemetry_enabled": False})
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
    assert "unified_enabled" not in new_source.call_args.kwargs
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
    assert "display_reported_state" not in attrs
    c.data["display_details"] = dict(
        c.data["display_details"], state="unknown", reported_state="off")
    attrs = entity.extra_state_attributes
    assert attrs["display_state"] == "unknown"
    assert attrs["display_reported_state"] == "off"



async def test_v3_requires_verified_discovery_not_just_local_config(hass):
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
    assert s.observed_game is None  # Never keep a stale game on screen.
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
        options={"unified_telemetry_enabled": False,
                 "tracked_apps": [APP], "enabled": True,
                 "daily": 320, "weekly": 4200},
    )
    entry.add_to_hass(hass)
    coordinator = co.GamingCoordinator(hass, entry)
    watcher, callbacks, _, _, _ = await start(hass, host)
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
    assert entities["active"].icon == "mdi:monitor"
    # A screen OFF report changes accounting to idle, but preserves the
    # independently verified Windows foreground in the same HA sensor.
    counted_before = total(watcher)
    with patch.object(co, "monotonic", return_value=10106):
        deliver(callbacks, root + "/state/telemetry",
                v3(host, ts=106, seq=4, screen="off", event=2), ts=106)
    assert coordinator.data["active_game"] == "idle"
    assert coordinator.data["observed_game"] == "Roblox"
    assert entities["active"].native_value == "Roblox"
    assert entities["active"].icon == "mdi:monitor-off"
    assert total(watcher) == counted_before
    with patch.object(co, "monotonic", return_value=10108):
        deliver(callbacks, root + "/state/telemetry",
                v3(host, ts=108, seq=5, screen="off", event=2,
                   event_age=2000), ts=108)
    assert entities["active"].native_value == "Roblox"
    assert total(watcher) == counted_before
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
        options={"unified_telemetry_enabled": False,
                 "tracked_apps": [APP], "enabled": True,
                 "daily": 320, "weekly": 4200},
    )
    entry.add_to_hass(hass)
    coordinator = co.GamingCoordinator(hass, entry)
    watcher, callbacks, _, _, _ = await start(hass, old)
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


@pytest.mark.parametrize("seconds, expected", [
    (0, "0d 0h 0m 0s"), (1, "0d 0h 0m 1s"),
    (59, "0d 0h 0m 59s"), (60, "0d 0h 1m 0s"),
    (3599, "0d 0h 59m 59s"), (3600, "0d 1h 0m 0s"),
    (86399, "0d 23h 59m 59s"), (86400, "1d 0h 0m 0s"),
    (101529, "1d 4h 12m 9s"), (2**63 - 1, "106751991167300d 15h 30m 7s"),
])
async def test_direct_uptime_human_readable_boundaries(seconds, expected):
    from custom_components.hal_gaming_control.direct_mqtt import format_uptime
    assert format_uptime(seconds) == expected


@pytest.mark.parametrize("seconds", [None, -1, True, "42", 1.1, 2**63, float("nan")])
async def test_direct_uptime_invalid_seconds_are_unknown(seconds):
    from custom_components.hal_gaming_control.direct_mqtt import format_uptime
    assert format_uptime(seconds) is None


async def test_native_discovery_uptime_uses_same_text_format_as_direct():
    from jinja2 import Environment
    from windows_agent.gaming_control.discovery import discovery
    config = discovery("pc1", "Gaming PC")[
        "homeassistant/sensor/smarthouse_gaming_pc1_uptime/config"]
    assert config["unique_id"] == "smarthouse_gaming_pc1_uptime"
    assert config["entity_category"] == "diagnostic"
    assert "device_class" not in config
    assert "unit_of_measurement" not in config
    rendered = Environment().from_string(config["value_template"])
    for seconds, expected in (
        (0, "0d 0h 0m 0s"), (59, "0d 0h 0m 59s"),
        (60, "0d 0h 1m 0s"), (3600, "0d 1h 0m 0s"),
        (86400, "1d 0h 0m 0s"), (101529, "1d 4h 12m 9s"),
        (2**63 - 1, "106751991167300d 15h 30m 7s"),
    ):
        packet = {"version": 3, "device_id": "pc1", "system": {"uptime_seconds": seconds}}
        assert rendered.render(value_json=packet).strip() == expected
    for packet in (
        {"version": 3, "device_id": "pc2", "system": {"uptime_seconds": 60}},
        {"version": 2, "device_id": "pc1", "system": {"uptime_seconds": 60}},
        {"version": 3, "device_id": "pc1", "system": {"uptime_seconds": -1}},
        {"version": 3, "device_id": "pc1", "system": {"uptime_seconds": None}},
        {"version": 3, "device_id": "pc1", "system": {"uptime_seconds": True}},
        {"version": 3, "device_id": "pc1", "system": {"uptime_seconds": 2**63}},
        {},
    ):
        assert rendered.render(value_json=packet).strip() == "unavailable"
