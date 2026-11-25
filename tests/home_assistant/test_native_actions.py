"""Real HA native service actions (own domain, no button.press delegation)."""
import json
from pathlib import Path
from time import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import mqtt
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_fire_mqtt_message,
)

from custom_components.hal_gaming_control.const import DOMAIN
from custom_components.hal_gaming_control.parent_bonus import parent_bonus_total

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]


@pytest.fixture
def expected_lingering_timers():
    return True


CONTRACT = (Path(__file__).resolve().parents[1] / "contracts" / "v3"
            / "telemetry-foreground.json")


def packet(device_id, seq, *, process="RobloxPlayerBeta.exe", state="foreground"):
    raw = json.loads(CONTRACT.read_text(encoding="utf-8"))
    raw.update(device_id=device_id, sequence=seq, observed_at=time(), epoch="a" * 32)
    raw["foreground"].update(
        state=state, process=process if state == "foreground" else None,
        signature=None, sample_age_ms=0)
    raw["display"].update(
        state="unknown", event_epoch=None, event_sequence=None,
        event_age_ms=None, sample_age_ms=None)
    return raw


def send(hass, device, suffix, data):
    async_fire_mqtt_message(
        hass, f"SmartHouse/Gaming/{device}/{suffix}",
        json.dumps(data) if isinstance(data, dict) else data)


def discovery(device, *, ui=False):
    return {"protocol_version": 1, "device_id": device, "name": device,
            "games": [], "actions": ["lock_pc"],
            "unified_telemetry_protocol": 3,
            **({"popup_ui_protocol": 1} if ui else {})}


async def setup_device(hass, device="pc1", *, direct=False, options=None):
    data = {"device_id": device, "name": device,
            "protocol_version": 1, "games": [], "actions": ["lock_pc"]}
    entry = MockConfigEntry(
        domain=DOMAIN, title=device, unique_id=device, data=data,
        options=options if options is not None else {
            "daily": 180, "weekly": 300,
            "tracked_apps": [{"name": "Roblox",
                              "process": "RobloxPlayerBeta.exe",
                              "signature": None}]})
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
               return_value=direct):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, device + "_terminate_tracked_game")
    assert entity_id is not None
    ha_device_id = er.async_get(hass).async_get(entity_id).device_id
    assert dr.async_get(hass).async_get(ha_device_id) is not None
    return entry, ha_device_id


async def make_fresh(hass, device="pc1", *, ui=False):
    send(hass, device, "discovery", discovery(device, ui=ui))
    send(hass, device, "availability", "online")
    send(hass, device, "state/telemetry", packet(device, 1))
    await hass.async_block_till_done()
    send(hass, device, "state/telemetry", packet(device, 2))
    await hass.async_block_till_done()


async def call(hass, name, device_id, **data):
    await hass.services.async_call(
        DOMAIN, name, {"device_id": device_id, **data}, blocking=True)


@pytest.mark.parametrize("direct", [False, True])
async def test_custom_actions_registered_in_ha_and_reject_stale_lock(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry, device_id = await setup_device(hass, direct=direct)
    for name in ("lock_pc", "terminate_game", "add_bonus", "set_unlimited", "popup"):
        assert hass.services.has_service(DOMAIN, name)

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        with pytest.raises(HomeAssistantError):
            await call(hass, "lock_pc", device_id)
        publish.assert_not_called()
        await make_fresh(hass)
        assert entry.runtime_data.foreground.current() == "Roblox"
        await call(hass, "lock_pc", device_id)
        publish.assert_awaited_once_with(
            hass, "SmartHouse/Gaming/pc1/command/lock_pc",
            "PRESS", qos=0, retain=False)
        send(hass, "pc1", "availability", "offline")
        await hass.async_block_till_done()
        with pytest.raises(HomeAssistantError):
            await call(hass, "lock_pc", device_id)
        assert publish.await_count == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("direct", [False, True])
async def test_native_terminate_shares_single_use_capability_with_button(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry, device_id = await setup_device(hass, direct=direct)
    await make_fresh(hass)
    source = entry.runtime_data.foreground
    assert source.last_raw is not None
    raw = source.last_raw
    offer = {key: raw[key] for key in (
        "device_id", "epoch", "sequence", "observed_at", "process", "signature")}
    offer.update(version=1, token="b" * 32)
    send(hass, "pc1", "state/terminate_offer", offer)
    await hass.async_block_till_done()
    assert entry.runtime_data.termination.available

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        await call(hass, "terminate_game", device_id)
        assert publish.await_count == 1
        assert publish.call_args.args[:2] == (
            hass, "SmartHouse/Gaming/pc1/command/terminate_target")
        sent = json.loads(publish.call_args.args[2])
        assert sent["token"] == "b" * 32
        assert sent["device_id"] == "pc1"
        assert not entry.runtime_data.termination.available
        with pytest.raises(HomeAssistantError):
            await call(hass, "terminate_game", device_id)
        assert publish.await_count == 1

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_smart_parent_actions_require_verified_budget_but_never_publish_commands(
        hass, enable_custom_integrations, mqtt_mock):
    entry, device_id = await setup_device(hass, options={
        "enabled": True, "daily": 180, "weekly": 4200, "unlimited": False})
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        with pytest.raises(HomeAssistantError):
            await call(hass, "add_bonus", device_id, minutes=15)
        assert "parent_bonus_journal" not in entry.options
        await make_fresh(hass)
        await call(hass, "add_bonus", device_id, minutes=15)
        await hass.async_block_till_done()
        from custom_components.hal_gaming_control.parent_bonus import parent_smart_grants
        stamp = __import__("homeassistant.util.dt", fromlist=["now"]).now()
        assert sum(row.daily_seconds for row in parent_smart_grants(entry.options, "pc1", stamp).values()) == 900
        assert entry.options["weekly"] == 4200
        await call(hass, "set_unlimited", device_id, enabled=True)
        await hass.async_block_till_done()
        assert entry.options["unlimited"] is True
        await call(hass, "set_unlimited", device_id, enabled=False)
        assert entry.options["unlimited"] is False
        publish.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("hide_fields", [
    {},
    {"heading": "Old heading", "description": "Old detail",
     "remaining_seconds": 45, "progress_percent": 8,
     "buttons": [{"id": "ok", "text": "OK", "color": "neutral"}]},
    {"heading": "", "description": "", "remaining_seconds": -1,
     "progress_percent": 101, "buttons": "invalid stale form value"},
    {"buttons": [{"id": "ok", "text": "OK", "color": "neutral"}] * 2},
])
async def test_popup_action_requires_advertised_agent_and_sends_fixed_ui_contract(
        hass, enable_custom_integrations, mqtt_mock, hide_fields):
    entry, device_id = await setup_device(hass)
    await make_fresh(hass, ui=False)
    buttons = [
        {"id": "ok", "text": "OK", "color": "neutral"},
        {"id": "more", "text": "Request more time", "color": "primary"},
    ]
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        with pytest.raises(HomeAssistantError, match="popup UI protocol"):
            await call(hass, "popup", device_id, heading="Gaming time remaining",
                       description="Weekly budget", remaining_seconds=598,
                       progress_percent=24, buttons=buttons)
        publish.assert_not_called()
        send(hass, "pc1", "discovery", discovery("pc1", ui=True))
        await hass.async_block_till_done()
        await call(hass, "popup", device_id, heading="Gaming time remaining",
                   description="Weekly budget", remaining_seconds=598,
                   progress_percent=24, buttons=buttons)
        assert publish.await_count == 1
        args = publish.call_args
        assert args.args[:2] == (hass, "SmartHouse/Gaming/pc1/ui/popup")
        assert args.kwargs == {"qos": 1, "retain": False}
        first = json.loads(args.args[2])
        assert first["version"] == 1 and first["operation"] == "upsert"
        assert first["view"]["remaining_seconds"] == 598
        assert first["display_stale_after_seconds"] > 598  # local tick reaches zero
        assert first["view"]["buttons"] == buttons
        await call(hass, "popup", device_id, heading="Another update",
                   remaining_seconds=45, progress_percent=8, buttons=[])
        second = json.loads(publish.call_args.args[2])
        assert second["popup_id"] == first["popup_id"]
        assert second["sequence"] > first["sequence"]
        await call(hass, "popup", device_id, operation="hide", **hide_fields)
        assert publish.await_count == 3
        hidden = json.loads(publish.call_args.args[2])
        assert hidden["operation"] == "hide" and "view" not in hidden
        assert hidden["popup_id"] == first["popup_id"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_actions_are_device_scoped_and_no_cross_pc_broadcast(
        hass, enable_custom_integrations, mqtt_mock):
    a, one = await setup_device(hass, "pc1")
    b, two = await setup_device(hass, "pc2")
    await make_fresh(hass, "pc1")
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        await call(hass, "lock_pc", one)
        assert publish.call_args.args[1] == "SmartHouse/Gaming/pc1/command/lock_pc"
        with pytest.raises(HomeAssistantError):
            await call(hass, "lock_pc", two)
        assert publish.await_count == 1
    assert await hass.config_entries.async_unload(a.entry_id)
    assert await hass.config_entries.async_unload(b.entry_id)



async def test_popup_response_ids_are_scoped_deduplicated_and_non_authoritative(
        hass, enable_custom_integrations, mqtt_mock):
    """Child UI clicks are events, not automatic bonus or OS commands."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    entry, device_id = await setup_device(hass)
    await make_fresh(hass, ui=True)
    events = []
    unsub = hass.bus.async_listen(
        "hal_gaming_control_popup_response", lambda event: events.append(event.data))
    before_options = dict(entry.options)
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        await call(hass, "popup", device_id,
                   heading="Gaming time remaining", description="Weekly budget",
                   remaining_seconds=598, progress_percent=24,
                   buttons=[{"id": "request_more", "text": "More time", "color": "primary"}])
        outgoing = json.loads(publish.call_args.args[2])
        response = {
            "version": 1, "device_id": "pc1", "popup_id": outgoing["popup_id"],
            "event_id": "c" * 32, "kind": "button", "button_id": "request_more",
        }
        def receive(value, retain=False):
            entry.runtime_data.popup._on_popup_event(SimpleNamespace(
                topic="SmartHouse/Gaming/pc1/ui/popup_event",
                payload=json.dumps(value), retain=retain))
        receive(response, retain=True)
        receive(response | {"device_id": "pc2"})
        receive(response | {"button_id": "not_approved"})
        receive(response | {"popup_id": "e" * 32})
        receive(response)
        receive(response)  # MQTT QoS 1 duplicate
        await hass.async_block_till_done()
        assert len(events) == 1
        assert events[0]["button_id"] == "request_more"
        assert events[0]["device_id"] == "pc1"
        assert entry.options == before_options  # no Parent bonus granted
        assert publish.await_count == 1

        # Closing is distinct from a button event and has no button_id.
        receive({k: v for k, v in (response | {
            "kind": "closed", "event_id": "d" * 32}).items() if k != "button_id"})
        await hass.async_block_till_done()
        assert len(events) == 2
        assert events[-1]["kind"] == "closed"
        assert "button_id" not in events[-1]
    unsub()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_smart_threshold_trigger_crosses_once_and_rearms(hass):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from homeassistant.helpers.trigger import TriggerConfig
    from custom_components.hal_gaming_control.trigger import RemainingBudgetTrigger

    config = await RemainingBudgetTrigger.async_validate_config(hass, {
        "options": {"minutes": 10, "device_id": ["device-a", "device-b"]}})
    trigger = RemainingBudgetTrigger(hass, TriggerConfig(
        key=DOMAIN + ".remaining_budget_reached", options=config["options"]))
    registry = Mock()
    registry.async_get.side_effect = lambda entity_id: {
        "sensor.a": SimpleNamespace(platform=DOMAIN, unique_id="a_gaming_budget_remaining", device_id="device-a"),
        "sensor.b": SimpleNamespace(platform=DOMAIN, unique_id="b_gaming_budget_remaining", device_id="device-b"),
        "sensor.c": SimpleNamespace(platform=DOMAIN, unique_id="c_gaming_budget_remaining", device_id="device-c"),
        "sensor.foreign": SimpleNamespace(platform="other", unique_id="a_gaming_budget_remaining", device_id="device-a"),
    }.get(entity_id)
    action = Mock()
    def put(entity, seconds, status="limited"):
        hass.states.async_set(entity, seconds / 60 if seconds is not None else "unknown",
                              {"remaining_seconds": seconds, "budget_status": status})
    with patch("custom_components.hal_gaming_control.trigger.er.async_get", return_value=registry):
        detach = await trigger.async_attach_runner(action)
        put("sensor.a", 599)  # startup inside range: no warning
        put("sensor.a", 580)
        put("sensor.a", 700)
        put("sensor.a", 600)
        put("sensor.a", 590)
        put("sensor.b", 700)
        put("sensor.b", 550)
        put("sensor.c", 700)
        put("sensor.c", 590)
        put("sensor.foreign", 700)
        put("sensor.foreign", 590)
        put("sensor.a", None, "unknown")
        put("sensor.a", 500)  # reconnect: no warning
        put("sensor.a", 800)
        put("sensor.a", 0)  # obsolete positive warning suppressed
        put("sensor.a", 1000)
        put("sensor.a", 400)
        await hass.async_block_till_done()
        assert [call.args[0]["device_id"] for call in action.call_args_list] == [
            "device-a", "device-b", "device-a"]
        assert [call.args[0]["remaining_seconds"] for call in action.call_args_list] == [600, 550, 400]
        detach()
        put("sensor.a", 700)
        put("sensor.a", 600)
        await hass.async_block_till_done()
        assert action.call_count == 3


async def test_smart_threshold_zero_any_device_and_validation(hass):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import probatio
    from homeassistant.helpers.trigger import TriggerConfig
    from custom_components.hal_gaming_control.trigger import RemainingBudgetTrigger
    for value in (-1, True, 1.5, 10081):
        with pytest.raises(probatio.Invalid):
            await RemainingBudgetTrigger.async_validate_config(hass, {"options": {"minutes": value}})
    config = await RemainingBudgetTrigger.async_validate_config(hass, {"options": {"minutes": 0}})
    trigger = RemainingBudgetTrigger(hass, TriggerConfig(key=DOMAIN + ".remaining_budget_reached",
                                                         options=config["options"]))
    registry = Mock()
    registry.async_get.return_value = SimpleNamespace(
        platform=DOMAIN, unique_id="pc_gaming_budget_remaining", device_id="pc")
    action = Mock()
    with patch("custom_components.hal_gaming_control.trigger.er.async_get", return_value=registry):
        detach = await trigger.async_attach_runner(action)
        hass.states.async_set("sensor.pc", 1, {"remaining_seconds": 60, "budget_status": "limited"})
        hass.states.async_set("sensor.pc", 0, {"remaining_seconds": 0, "budget_status": "limited"})
        hass.states.async_set("sensor.pc", 0, {"remaining_seconds": 0, "budget_status": "limited", "extra": True})
        await hass.async_block_till_done()
        assert action.call_count == 1
        assert action.call_args.args[0]["device_id"] == "pc"
        detach()


async def test_popup_automatic_fields_use_effective_budget_independently(
        hass, enable_custom_integrations, mqtt_mock):
    entry, device_id = await setup_device(hass, options={
        "enabled": True, "daily": 60, "weekly": 300, "schedule_enabled": False})
    await make_fresh(hass, ui=True)
    c = entry.runtime_data
    with patch.object(c, "async_refresh", new_callable=AsyncMock), \
         patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        c.data = {"ready": True, "totals": {"daily": 3000, "weekly": 3000}}
        await call(hass, "popup", device_id, heading="Warning",
                   countdown_mode="automatic", progress_mode="automatic",
                   description_mode="automatic")
        view = json.loads(publish.call_args.args[2])["view"]
        assert view["remaining_seconds"] == 600
        assert view["progress_percent"] == pytest.approx(100 / 6)
        assert view["description"] == "Daily budget"
        await call(hass, "popup", device_id, heading="Warning",
                   countdown_mode="automatic", progress_percent=42)
        view = json.loads(publish.call_args.args[2])["view"]
        assert view["remaining_seconds"] == 600
        assert view["progress_percent"] == 42
        await call(hass, "popup", device_id, heading="Warning",
                   remaining_seconds=50, progress_mode="automatic")
        view = json.loads(publish.call_args.args[2])["view"]
        assert view["remaining_seconds"] == 50
        assert view["progress_percent"] == pytest.approx(100 / 6)
        c.data = {"ready": False, "totals": {}}
        count = publish.await_count
        with pytest.raises(HomeAssistantError, match="finite effective budget"):
            await call(hass, "popup", device_id, heading="Warning",
                       countdown_mode="automatic", progress_mode="automatic")
        assert publish.await_count == count
        await call(hass, "popup", device_id, operation="hide",
                   countdown_mode="stale", progress_mode="stale")
        assert json.loads(publish.call_args.args[2])["operation"] == "hide"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_v2_popup_shared_wire_refresh_and_dismissal(hass, enable_custom_integrations, mqtt_mock):
    from types import SimpleNamespace
    from time import time
    entry, device_id = await setup_device(hass, options={
        "enabled": True, "daily": 60, "weekly": 300, "schedule_enabled": False})
    await make_fresh(hass, ui=True)
    send(hass, "pc1", "discovery", discovery("pc1", ui=True) | {"popup_ui_protocols": [1, 2]})
    await hass.async_block_till_done()
    c = entry.runtime_data
    fixtures = Path(__file__).resolve().parents[1] / "contracts" / "v2"
    def assert_wire(packet, name):
        expected = json.loads((fixtures / ("popup-" + name + ".json")).read_text())
        assert abs(packet["issued_at"] - time()) < 10
        assert len(packet["producer_epoch"]) == len(packet["popup_id"]) == 32
        assert packet | {"issued_at": expected["issued_at"],
                         "producer_epoch": expected["producer_epoch"],
                         "popup_id": expected["popup_id"]} == expected
    with patch.object(c, "async_refresh", new_callable=AsyncMock), \
         patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        c.data = {"ready": True, "active_game": "Roblox",
                  "totals": {"daily": 1800, "weekly": 1800}}
        await call(hass, "popup", device_id, heading="Gaming time remaining",
                   countdown_mode="hidden", progress_mode="automatic",
                   description_mode="automatic")
        initial = json.loads(publish.call_args.args[2])
        assert_wire(initial, "upsert")
        c.data = {"ready": True, "active_game": "idle",
                  "totals": {"daily": 2160, "weekly": 2160}}
        await c.popup.async_sync()
        refresh = json.loads(publish.call_args.args[2])
        assert_wire(refresh, "refresh")
        assert refresh["popup_id"] == initial["popup_id"]
        c.popup._on_popup_event(SimpleNamespace(topic="SmartHouse/Gaming/pc1/ui/popup_event",
            retain=False, payload=json.dumps({"version": 1, "device_id": "pc1",
            "popup_id": initial["popup_id"], "event_id": "c"*32, "kind": "closed"})))
        before = publish.await_count
        await c.popup.async_sync()
        assert publish.await_count == before
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_hidden_popup_mode_requires_v2_and_ignores_stale_values(hass, enable_custom_integrations, mqtt_mock):
    entry, device_id = await setup_device(hass)
    await make_fresh(hass, ui=True)
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        with pytest.raises(HomeAssistantError, match="v2"):
            await call(hass, "popup", device_id, heading="Notice",
                       countdown_mode="hidden", progress_mode="hidden")
        publish.assert_not_called()
        send(hass, "pc1", "discovery", discovery("pc1", ui=True) | {"popup_ui_protocols": [1, 2]})
        await hass.async_block_till_done()
        await call(hass, "popup", device_id, heading="Notice", countdown_mode="hidden",
                   progress_mode="hidden", remaining_seconds=-5, progress_percent=101)
        packet = json.loads(publish.call_args.args[2])
        assert packet["version"] == 2
        assert packet["view"]["remaining_seconds"] is None
        assert packet["view"]["progress_percent"] is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_v2_live_popup_mixed_fields_bonus_pause_and_unknown(hass, enable_custom_integrations, mqtt_mock):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    entry, device_id = await setup_device(hass, options={
        "enabled": True, "daily": 60, "weekly": 300, "schedule_enabled": False})
    await make_fresh(hass, ui=True)
    send(hass, "pc1", "discovery", discovery("pc1", ui=True) | {"popup_ui_protocols": [1, 2]})
    await hass.async_block_till_done()
    c = entry.runtime_data
    stamp = datetime(2026, 11, 25, 21, 50, tzinfo=ZoneInfo("Europe/Zagreb"))
    with patch.object(c, "async_refresh", new_callable=AsyncMock), \
         patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish, \
         patch("custom_components.hal_gaming_control.popup_view.dt_util.now", return_value=stamp):
        c.data = {"ready": True, "active_game": "idle",
                  "totals": {"daily": 1800, "weekly": 1800}}
        await call(hass, "popup", device_id, heading="Warning",
                   countdown_mode="automatic", progress_percent=42)
        initial = json.loads(publish.call_args.args[2])
        assert initial["view"]["countdown_running"] is False
        assert initial["view"]["progress_seconds"] is None
        c.data["active_game"] = "Roblox"
        await c.popup.async_sync()
        patch_view = json.loads(publish.call_args.args[2])["view"]
        assert patch_view == {"remaining_seconds": 1800, "countdown_running": True}
        # A live setting update changes the limiting source. A schedule ticks
        # while idle, unlike a quota; manual progress is never reanchored.
        c.data["active_game"] = "idle"
        hass.config_entries.async_update_entry(entry, options=entry.options | {
            "schedule_enabled": True, "schedule_start": "16:00", "schedule_end": "22:00"})
        await c.popup.async_sync()
        assert json.loads(publish.call_args.args[2])["view"] == {
            "remaining_seconds": 600, "countdown_running": True}
        c.data = {"ready": False, "totals": {}}
        await c.popup.async_sync()
        assert json.loads(publish.call_args.args[2])["operation"] == "hide"
        count = publish.await_count
        c.data = {"ready": True, "active_game": "Roblox",
                  "totals": {"daily": 1800, "weekly": 1800}}
        await c.popup.async_sync()
        assert publish.await_count == count
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_mqtt_callbacks_run_on_ha_event_loop_and_only_notify_terminate(
        hass, enable_custom_integrations, mqtt_mock):
    """#263: use MQTT dispatch, not a direct invocation of the handler."""
    from homeassistant.core import is_callback

    entry, _ = await setup_device(hass)
    await make_fresh(hass)
    coordinator = entry.runtime_data
    target = coordinator.termination
    for handler in (target._on_offer, coordinator.popup._on_discovery,
                    coordinator.popup._on_popup_event):
        assert is_callback(handler)
    raw = coordinator.foreground.last_raw
    offer = {key: raw[key] for key in (
        "device_id", "epoch", "sequence", "observed_at", "process", "signature")}
    offer.update(version=1, token="b" * 32)
    eid = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, "pc1_terminate_tracked_game")
    with patch.object(coordinator, "async_update_listeners",
                      wraps=coordinator.async_update_listeners) as refresh:
        for _ in range(3):
            send(hass, "pc1", "state/terminate_offer", offer)
            await hass.async_block_till_done()
            assert hass.states.get(eid).state != "unavailable"
        send(hass, "pc1", "state/terminate_offer", {"invalid": True})
        await hass.async_block_till_done()
        assert hass.states.get(eid).state == "unavailable"
        refresh.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)
