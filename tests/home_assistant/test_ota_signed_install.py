"""Issue #166: signed OTA v2 handoff + fail-closed HA Install ordering."""
import asyncio
import base64
import hashlib
import json
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


PC = "pc1"
TID = "c" * 32
SETTINGS = {
    "device_id": PC, "installed": "0.2.10", "approved": "0.2.11",
    "version": "0.2.11", "online": True, "remote_update": True,
    "ota_protocol": 2, "base_url": "https://releases.example.invalid/win",
    "pinned_public_key": "Operator-pinned public PEM only",
}


def test_v2_is_required_and_staging_only_v1_cannot_be_a_signed_install():
    assert require_candidate(**SETTINGS, signed_handoff=True) is None
    for change in ({"ota_protocol": 1}, {"online": False},
                   {"remote_update": False}, {"approved": "0.2.12"},
                   {"pinned_public_key": None}):
        with pytest.raises(OtaPreflightError):
            require_candidate(**(SETTINGS | change), signed_handoff=True)


@pytest.mark.asyncio
async def test_pipeline_passes_exact_signed_manifest_and_requires_authenticated_ack(tmp_path):
    archive = SimpleNamespace(path=tmp_path / "trusted.zip", version="0.2.11",
                              sha256="d" * 64, size=123,
                              manifest=b'{"version":"0.2.11"}',
                              signature=b"z" * 64)
    cache, broker = Mock(), Mock()
    cache.async_prepare = AsyncMock(return_value=archive)
    broker.async_stage_package = AsyncMock(return_value={
        "status": "authenticated_staged", "version": "0.2.11",
        "transfer_id": TID})
    p = OtaStagingPipeline(None, tmp_path, cache=cache, transport=broker)
    receipt = await p.async_stage_approved(**SETTINGS, signed_handoff=True)
    assert receipt["status"] == "authenticated_staged"
    broker.async_stage_package.assert_awaited_once_with(
        archive.path, device_id=PC, version="0.2.11",
        expected_sha256=archive.sha256, expected_size=archive.size,
        on_progress=None, signed_manifest=archive.manifest,
        signed_signature=archive.signature)
    broker.async_stage_package.return_value = {
        "status": "staged_unverified", "version": "0.2.11",
        "transfer_id": TID}
    with pytest.raises(OtaPreflightError, match="did not confirm"):
        await p.async_stage_approved(**SETTINGS, signed_handoff=True)


class SignedBroker:
    """Minimal deterministic MQTT v2 Windows ACK simulator, no real broker."""

    def __init__(self, *, reject_auth=False, lose_auth=False):
        self.callback = None
        self.calls = []
        self.device_id = None
        self.transfer_id = None
        self.index = 0
        self.reject_auth = reject_auth
        self.lose_auth = lose_auth

    async def subscribe(self, hass, topic, callback, *, qos):
        self.callback = callback
        assert topic == f"SmartHouse/Gaming/{PC}/ota/ack" and qos == 1
        return lambda: None

    async def publish(self, hass, topic, payload, *, qos, retain):
        assert retain is False and qos == 1
        op = topic.rsplit("/", 1)[-1]
        self.calls.append((op, payload))
        if op == "start":
            o = json.loads(payload)
            self.device_id, self.transfer_id = o["device_id"], o["transfer_id"]
            self.index = 0
        if op == "chunk":
            self.index += 1
        if op == "auth":
            envelope = json.loads(payload)
            assert envelope == {
                "protocol": 2, "device_id": PC, "transfer_id": self.transfer_id,
                "manifest_b64": base64.b64encode(b"authentic manifest").decode(),
                "signature_b64": base64.b64encode(b"a" * 64).decode()}
            if self.lose_auth:
                return
        status = ("rejected" if op == "auth" and self.reject_auth else
                  "authenticated" if op == "auth" else
                  "staged" if op == "finish" else "receiving")
        ack = json.dumps({"protocol": 1, "device_id": self.device_id,
                          "transfer_id": self.transfer_id, "next_index": self.index,
                          "status": status})
        self.callback(SimpleNamespace(payload=ack, retain=False))


@pytest.mark.asyncio
async def test_transport_requires_auth_ack_after_zip_staging(monkeypatch, tmp_path):
    archive = tmp_path / "release.zip"
    archive.write_bytes(b"signed package payload")
    broker = SignedBroker()
    import custom_components.hal_gaming_control.ota_transport as module
    monkeypatch.setattr(module.mqtt, "async_publish", broker.publish)
    monkeypatch.setattr(module.mqtt, "async_subscribe", broker.subscribe)
    hass = Mock()
    async def executor(func, *args):
        return func(*args)
    hass.async_add_executor_job = executor
    result = await HaOtaTransport(hass).async_stage_package(
        archive, device_id=PC, version="0.2.11", transfer_id=TID,
        signed_manifest=b"authentic manifest", signed_signature=b"a"*64)
    assert result["status"] == "authenticated_staged"
    assert [op for op, _ in broker.calls] == [
        "start", "chunk", "finish", "auth"]
    bad = SignedBroker(reject_auth=True)
    monkeypatch.setattr(module.mqtt, "async_publish", bad.publish)
    monkeypatch.setattr(module.mqtt, "async_subscribe", bad.subscribe)
    with pytest.raises(OtaTransferError, match="rejected"):
        await HaOtaTransport(hass).async_stage_package(
            archive, device_id=PC, version="0.2.11", transfer_id=TID,
            signed_manifest=b"authentic manifest", signed_signature=b"a"*64)


def make_entity():
    c = Mock()
    c.device_id = PC
    c.entry.data = {"device_id": PC, "name": "Test PC"}
    c.entry.options = {
        "ota_install_enabled": True,
        "ota_release_base_url": SETTINGS["base_url"],
        "ota_signer_public_key": SETTINGS["pinned_public_key"],
        "update_catalog_url": "https://releases.example.invalid/catalog.json",
    }
    c.data = {"online": True}
    e = WindowsAgentUpdate(c)
    e.hass = Mock()
    e.installed, e.approved = "0.2.10", "0.2.11"
    e.capable, e.ota_protocol, e.ota_install_capable = True, 2, True
    e.async_write_ha_state = Mock()
    return e


@pytest.mark.asyncio
async def test_install_sends_windows_command_only_after_signed_v2_receipt():
    e = make_entity()
    stages = []
    async def stage(version, *, signed_handoff):
        assert version == "0.2.11" and signed_handoff is True
        stages.append("authenticated")
        return {"status": "authenticated_staged", "version": version}
    e._async_stage_signed_ota_candidate = stage
    e._refresh_catalog = AsyncMock()
    async def publish(*args, **kwargs):
        assert stages == ["authenticated"]
        stages.append("command")
    with patch("custom_components.hal_gaming_control.update.mqtt.async_publish",
               side_effect=publish):
        await e.async_install("0.2.11", False)
    assert stages == ["authenticated", "command"]
    assert e.pending["version"] == "0.2.11"
    assert e.result == "requested"


@pytest.mark.asyncio
async def test_bad_auth_or_nonv2_pc_never_gets_install_command():
    e = make_entity()
    e._refresh_catalog = AsyncMock()
    e._async_stage_signed_ota_candidate = AsyncMock(
        side_effect=HomeAssistantError("signature or ACK invalid"))
    with patch("custom_components.hal_gaming_control.update.mqtt.async_publish",
               new_callable=AsyncMock) as publish:
        with pytest.raises(HomeAssistantError):
            await e.async_install("0.2.11", False)
        publish.assert_not_awaited()
    assert e.pending is None
    assert e.result == "ota_preflight_failed"
    e.ota_protocol = 1
    assert e.available is False


def test_discovery_cannot_invent_ota_install_readiness():
    e = make_entity()
    with patch.object(e, "async_write_ha_state"):
        e._metadata(SimpleNamespace(
            topic=f"SmartHouse/Gaming/{PC}/discovery",
            payload=json.dumps({"protocol_version": 1, "device_id": PC,
                                "name": "Test PC", "actions": [], "games": [],
                                "agent_version": "0.2.11",
                                "remote_update": True, "mqtt_ota_protocol": 1,
                                "mqtt_ota_install_ready": True})))
    assert e.ota_protocol == 1
    assert e.ota_install_capable is False
    assert e.extra_state_attributes["mqtt_ota_install_ready"] is False



@pytest.mark.asyncio
@pytest.mark.usefixtures("recorder_mock")
async def test_native_admin_options_flow_requires_fixed_urls_and_pinned_public_ed25519(
        hass, enable_custom_integrations):
    from homeassistant.data_entry_flow import FlowResultType
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from custom_components.hal_gaming_control.const import DOMAIN

    saved = {"daily": 120, "tracked_apps": [{"name": "Roblox",
                                              "process": "RobloxPlayerBeta.exe"}]}
    entry = MockConfigEntry(domain=DOMAIN, data={
        "device_id": PC, "name": "Windows PC", "protocol_version": 1,
        "games": [], "actions": ["lock_pc"],
    }, unique_id=PC, options=saved)
    entry.add_to_hass(hass)
    manager = hass.config_entries.options
    menu = await manager.async_init(entry.entry_id)
    assert "windows_updates" in menu["menu_options"]
    form = await manager.async_configure(
        menu["flow_id"], {"next_step_id": "windows_updates"})
    assert form["type"] == FlowResultType.FORM
    public = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    invalid = await manager.async_configure(form["flow_id"], {
        "ota_install_enabled": True,
        "update_catalog_url": "http://insecure.example/catalog.json",
        "ota_release_base_url": "https://releases.example.invalid/windows",
        "ota_signer_public_key": public})
    assert invalid["type"] == FlowResultType.FORM
    assert invalid["errors"]["base"] == "invalid_signed_release"
    assert entry.options == saved

    values = {
        "ota_install_enabled": True,
        "update_catalog_url": "https://releases.example.invalid/catalog.json",
        "ota_release_base_url": "https://releases.example.invalid/windows",
        "ota_signer_public_key": public,
    }
    result = await manager.async_configure(form["flow_id"], values)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["daily"] == 120
    assert result["data"]["tracked_apps"] == saved["tracked_apps"]
    assert result["data"]["ota_install_enabled"] is True
    assert result["data"]["ota_signer_public_key"] == public
