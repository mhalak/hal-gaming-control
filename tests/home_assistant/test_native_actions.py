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


async def test_parent_only_actions_work_offline_without_mqtt_commands(
        hass, enable_custom_integrations, mqtt_mock):
    entry, device_id = await setup_device(hass, options={
        "daily": 180, "weekly": 4200, "unlimited": False})
    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        await call(hass, "add_bonus", device_id, minutes=15)
        await hass.async_block_till_done()
        assert parent_bonus_total(entry.options, __import__(
            "homeassistant.util.dt", fromlist=["now"]).now()) == 15
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
