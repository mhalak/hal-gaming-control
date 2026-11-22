"""Real HA + MQTT manual single-target action (both MQTT installation modes)."""
import json
from time import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import mqtt
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_fire_mqtt_message,
)

from custom_components.hal_gaming_control.const import DOMAIN

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("recorder_mock")]


@pytest.fixture
def expected_lingering_timers():
    return True


ROOT = "SmartHouse/Gaming/pc1"
DATA = {"device_id": "pc1", "name": "PC 1", "protocol_version": 1,
        "games": [], "actions": ["lock_pc"]}


def raw(t, seq=1, *, state="foreground", process="RobloxPlayerBeta.exe"):
    return {"version": 2, "device_id": "pc1", "epoch": "a" * 32,
            "sequence": seq, "observed_at": t, "state": state,
            "process": process if state == "foreground" else None,
            "signature": None}


def offer(sample):
    return {"version": 1, "device_id": "pc1", "epoch": sample["epoch"],
            "sequence": sample["sequence"], "observed_at": sample["observed_at"],
            "process": sample["process"], "signature": sample["signature"],
            "token": "b" * 32}


async def emit(hass, suffix, value, device="pc1"):
    async_fire_mqtt_message(
        hass, f"SmartHouse/Gaming/{device}/{suffix}",
        json.dumps(value) if isinstance(value, dict) else value)
    await hass.async_block_till_done()


@pytest.mark.parametrize("direct", [False, True])
async def test_manual_targeted_action_never_sends_unauthorized_kill(
        hass, enable_custom_integrations, mqtt_mock, direct):
    entry = MockConfigEntry(
        domain=DOMAIN, title="PC 1", unique_id="pc1", data=DATA,
        options={"tracked_apps": [
            {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}]})
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
               return_value=direct):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    reg = er.async_get(hass)
    eid = reg.async_get_entity_id("button", DOMAIN, "pc1_terminate_tracked_game")
    assert eid
    # The old native MQTT button must not be duplicated by the new HA action.
    assert reg.async_get_entity_id("button", "mqtt",
                                   "smarthouse_gaming_pc1_terminate_tracked_game") is None
    assert hass.states.get(eid).state == "unavailable"

    with patch.object(mqtt, "async_publish", new_callable=AsyncMock) as publish:
        t = time()
        await emit(hass, "availability", "online")
        sample = raw(t)
        await emit(hass, "state/foreground_identity", sample)
        await emit(hass, "state/terminate_offer", offer(sample) | {"device_id": "pc2"})
        assert hass.states.get(eid).state == "unavailable"
        await emit(hass, "state/terminate_offer", offer(sample))
        assert hass.states.get(eid).state != "unavailable"
        assert not publish.called

        await hass.services.async_call("button", "press",
                                       {"entity_id": eid}, blocking=True)
        assert publish.await_count == 1
        args = publish.call_args.args
        kwargs = publish.call_args.kwargs
        assert args[:2] == (hass, ROOT + "/command/terminate_target")
        req = json.loads(args[2])
        assert set(req) == {"version", "device_id", "epoch", "token", "request_id"}
        assert req["device_id"] == "pc1" and req["token"] == "b" * 32
        assert kwargs == {"qos": 0, "retain": False}
        assert hass.states.get(eid).state == "unavailable"
        await hass.services.async_call("button", "press",
                                       {"entity_id": eid}, blocking=True)
        assert publish.await_count == 1

        # Stale offer from the old foreground sequence cannot be reused.
        await emit(hass, "state/foreground_identity", raw(time(), seq=2, state="idle"))
        await emit(hass, "state/terminate_offer", offer(sample))
        assert hass.states.get(eid).state == "unavailable"
        await emit(hass, "availability", "offline")
        assert hass.states.get(eid).state == "unavailable"
        assert publish.await_count == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_untracked_foreground_never_exposes_termination(
        hass, enable_custom_integrations, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, title="PC 1", unique_id="pc1", data=DATA,
                            options={"tracked_apps": []})
    entry.add_to_hass(hass)
    with patch("custom_components.hal_gaming_control.coordinator.direct_mode",
               return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    eid = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, "pc1_terminate_tracked_game")
    assert eid
    sample = raw(time())
    await emit(hass, "availability", "online")
    await emit(hass, "state/foreground_identity", sample)
    await emit(hass, "state/terminate_offer", offer(sample))
    assert hass.states.get(eid).state == "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)
