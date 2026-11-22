"""HA-only signed-OTA candidate gate and staging composition, no installation."""
import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.hal_gaming_control.ota_pipeline import (
    OtaPreflightError, OtaStagingPipeline, require_candidate,
)
from custom_components.hal_gaming_control.ota_transport import (
    HaOtaTransport, OtaTransferError,
)
from custom_components.hal_gaming_control.update import WindowsAgentUpdate


SETTINGS = {
    "device_id": "pc1", "installed": "0.2.10",
    "approved": "0.2.11", "version": "0.2.11",
    "online": True, "remote_update": True, "ota_protocol": 1,
    "base_url": "https://releases.example.invalid/windows",
    "pinned_public_key": "PINNED ED25519 PEM",
}


class DummyHass:
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _preflight(**changes):
    return SETTINGS | changes


def test_approved_online_candidate_is_stage_eligible():
    assert require_candidate(**SETTINGS) is None


@pytest.mark.parametrize("changes", [
    {"online": False}, {"online": None},
    {"remote_update": False}, {"ota_protocol": None},
    {"ota_protocol": 2}, {"ota_protocol": True},
    {"device_id": ""}, {"version": "0.2.12"},
    {"approved": "0.2.12"}, {"installed": "0.2.11"},
    {"installed": "0.2.12"}, {"installed": "not-a-version"},
    {"base_url": ""}, {"base_url": None}, {"pinned_public_key": None},
])
def test_invalid_device_release_or_missing_key_never_reaches_cache(changes):
    with pytest.raises(OtaPreflightError):
        require_candidate(**_preflight(**changes))


@pytest.mark.asyncio
async def test_pipeline_pins_signed_digest_and_keeps_staging_unverified(tmp_path):
    signed = SimpleNamespace(path=tmp_path / "agent.zip", version="0.2.11",
                             sha256="a" * 64, size=128)
    cache = Mock()
    cache.async_prepare = AsyncMock(return_value=signed)
    broker = Mock()
    broker.async_stage_package = AsyncMock(return_value={
        "status": "staged_unverified", "version": "0.2.11",
        "transfer_id": "b" * 32, "chunks": 1,
    })
    pipeline = OtaStagingPipeline(None, tmp_path, cache=cache, transport=broker)
    progress = Mock()
    result = await pipeline.async_stage_approved(**SETTINGS, on_progress=progress)
    assert result["status"] == "staged_unverified"
    cache.async_prepare.assert_awaited_once_with(
        base_url=SETTINGS["base_url"], version="0.2.11",
        pinned_public_key=SETTINGS["pinned_public_key"])
    broker.async_stage_package.assert_awaited_once_with(
        signed.path, device_id="pc1", version="0.2.11",
        expected_sha256=signed.sha256, expected_size=signed.size,
        on_progress=progress)


@pytest.mark.asyncio
async def test_ineligible_pc_never_downloads_or_sends(tmp_path):
    cache = Mock()
    cache.async_prepare = AsyncMock()
    broker = Mock()
    broker.async_stage_package = AsyncMock()
    pipeline = OtaStagingPipeline(None, tmp_path, cache=cache, transport=broker)
    with pytest.raises(OtaPreflightError):
        await pipeline.async_stage_approved(**_preflight(online=False))
    cache.async_prepare.assert_not_awaited()
    broker.async_stage_package.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("archive", [
    SimpleNamespace(path="/tmp/ignored.zip", version="0.2.10", sha256="a"*64, size=100),
    SimpleNamespace(path="/tmp/ignored.zip", version="0.2.11", sha256="", size=100),
    SimpleNamespace(path="/tmp/ignored.zip", version="0.2.11", sha256="a"*64, size=0),
])
async def test_bad_cache_receipt_cannot_start_mqtt_staging(tmp_path, archive):
    cache, broker = Mock(), Mock()
    cache.async_prepare = AsyncMock(return_value=archive)
    broker.async_stage_package = AsyncMock()
    pipeline = OtaStagingPipeline(None, tmp_path, cache=cache, transport=broker)
    with pytest.raises(OtaPreflightError, match="metadata mismatch"):
        await pipeline.async_stage_approved(**SETTINGS)
    broker.async_stage_package.assert_not_awaited()


@pytest.mark.asyncio
async def test_staged_status_alone_never_becomes_installed(tmp_path):
    signed = SimpleNamespace(path=tmp_path/"agent.zip", version="0.2.11",
                             sha256="a"*64, size=128)
    cache, broker = Mock(), Mock()
    cache.async_prepare = AsyncMock(return_value=signed)
    broker.async_stage_package = AsyncMock(return_value={
        "status": "success", "version": "0.2.11", "transfer_id": "b"*32})
    pipeline = OtaStagingPipeline(None, tmp_path, cache=cache, transport=broker)
    with pytest.raises(OtaPreflightError, match="did not confirm"):
        await pipeline.async_stage_approved(**SETTINGS)


@pytest.mark.asyncio
async def test_concurrent_staging_same_entity_refused(tmp_path):
    cache, broker = Mock(), Mock()
    running, continue_transfer = asyncio.Event(), asyncio.Event()
    async def prepare(**_kwargs):
        running.set()
        await continue_transfer.wait()
        return SimpleNamespace(path=tmp_path/"x.zip", version="0.2.11",
                               sha256="a"*64, size=128)
    cache.async_prepare = prepare
    broker.async_stage_package = AsyncMock(return_value={
        "status": "staged_unverified", "version": "0.2.11", "transfer_id": "f"*32})
    pipeline = OtaStagingPipeline(None, tmp_path, cache=cache, transport=broker)
    first = asyncio.create_task(pipeline.async_stage_approved(**SETTINGS))
    await asyncio.wait_for(running.wait(), timeout=2)
    with pytest.raises(OtaPreflightError, match="already running"):
        await pipeline.async_stage_approved(**SETTINGS)
    continue_transfer.set()
    assert (await first)["status"] == "staged_unverified"


@pytest.mark.asyncio
async def test_ota_sender_refuses_modified_archive_before_publish(tmp_path):
    source = tmp_path / "agent.zip"
    source.write_bytes(b"A" * 200)
    expected = hashlib.sha256(b"trusted different bytes").hexdigest()
    sender = HaOtaTransport(DummyHass())
    with patch("custom_components.hal_gaming_control.ota_transport.mqtt.async_subscribe",
               new_callable=AsyncMock) as sub, pytest.raises(
                   OtaTransferError, match="signed manifest digest"):
        await sender.async_stage_package(
            source, device_id="pc1", version="0.2.11",
            expected_sha256=expected, expected_size=source.stat().st_size)
    sub.assert_not_awaited()


@pytest.mark.asyncio
async def test_ota_sender_refuses_wrong_signed_size_before_publish(tmp_path):
    source = tmp_path / "agent.zip"
    source.write_bytes(b"A" * 200)
    sender = HaOtaTransport(DummyHass())
    with patch("custom_components.hal_gaming_control.ota_transport.mqtt.async_subscribe",
               new_callable=AsyncMock) as sub, pytest.raises(
                   OtaTransferError, match="signed manifest size"):
        await sender.async_stage_package(
            source, device_id="pc1", version="0.2.11",
            expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            expected_size=100)
    sub.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_entity_recognizes_staging_capability_without_install_authority(hass):
    config = {"device_id": "pc1", "name": "PC",
              "protocol_version": 1, "actions": ["lock_pc"], "games": []}
    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry.data = config
    coordinator.entry.options = {
        "ota_stage_preview_enabled": True,
        "ota_release_base_url": SETTINGS["base_url"],
        "ota_signer_public_key": SETTINGS["pinned_public_key"],
    }
    coordinator.data = {"online": True}
    entity = WindowsAgentUpdate(coordinator)
    entity.hass = hass
    entity.approved = "0.2.11"
    with patch.object(entity, "async_write_ha_state"):
        entity._metadata(SimpleNamespace(
            topic="SmartHouse/Gaming/pc1/discovery",
            payload=__import__("json").dumps(
                config | {"agent_version": "0.2.10", "remote_update": True,
                          "mqtt_ota_protocol": 1})))
    assert entity.ota_protocol == 1
    assert entity.extra_state_attributes["mqtt_ota_install_ready"] is False
    assert entity.extra_state_attributes["mqtt_ota_protocol"] == 1
    pipeline = Mock()
    pipeline.async_stage_approved = AsyncMock(return_value={
        "status": "staged_unverified", "version": "0.2.11", "transfer_id": "c"*32})
    entity._ota_pipeline = pipeline
    with patch("custom_components.hal_gaming_control.update.mqtt.async_publish",
               new_callable=AsyncMock) as publish:
        result = await entity._async_stage_signed_ota_candidate("0.2.11")
        assert result["status"] == "staged_unverified"
        publish.assert_not_awaited()  # Not command/update, not an installation.
    pipeline.async_stage_approved.assert_awaited_once()
    coordinator.entry.options = {}
    with pytest.raises(HomeAssistantError, match="disabled"):
        await entity._async_stage_signed_ota_candidate("0.2.11")


@pytest.mark.asyncio
async def test_ota_stage_preview_never_turns_legacy_install_into_ota(hass):
    coordinator = Mock()
    coordinator.device_id = "pc1"
    coordinator.entry.data = {"name": "PC", "device_id": "pc1"}
    coordinator.entry.options = {"ota_stage_preview_enabled": True}
    coordinator.data = {"online": False}
    entity = WindowsAgentUpdate(coordinator)
    entity.hass = hass
    entity.ota_protocol = 1
    entity._ota_pipeline = Mock()
    entity._ota_pipeline.async_stage_approved = AsyncMock()
    with pytest.raises(HomeAssistantError):
        await entity.async_install(None, False)
    entity._ota_pipeline.async_stage_approved.assert_not_awaited()
