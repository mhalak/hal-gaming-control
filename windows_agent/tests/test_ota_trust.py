"""Issue #166: exact signed MQTT v2 handoff to existing rollback updater."""
import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from gaming_control.ota_staging import StageReceiver, encode_chunk
from gaming_control.ota_trust import (
    OtaTrustError, authorize_staged, load_approved_staged, verify_signed_offer,
)

PC, TID, VERSION = "pc_1", "a" * 32, "2.0.0"


def pem(key):
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def staged(tmp_path, data, *, version=VERSION):
    receiver = StageReceiver(tmp_path, PC)
    offer = {"protocol": 1, "device_id": PC, "transfer_id": TID,
             "version": version, "sha256": hashlib.sha256(data).hexdigest(),
             "size": len(data), "chunk_size": 65536, "expires_at": 1060}
    receiver.start(json.dumps(offer), now=990)
    for index, at in enumerate(range(0, len(data), 65536)):
        receiver.receive(encode_chunk(TID, index, data[at:at + 65536]), now=991)
    receiver.finish(json.dumps({"protocol": 1, "device_id": PC,
                                "transfer_id": TID}), now=992)
    return receiver


def signed_auth(data, key, *, version=VERSION, **changes):
    raw = json.dumps({"version": version, "filename": f"windows-agent-{version}.zip",
                      "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                     sort_keys=True, separators=(",", ":")).encode()
    return json.dumps({
        "protocol": 2, "device_id": PC, "transfer_id": TID,
        "manifest_b64": base64.b64encode(raw).decode(),
        "signature_b64": base64.b64encode(key.sign(raw)).decode(),
    } | changes, separators=(",", ":")).encode()


def test_authorized_exact_signed_archive_is_durable_and_idempotent(tmp_path):
    from updater_fakes import signed_release
    key = Ed25519PrivateKey.generate()
    data = signed_release(key, VERSION)[f"windows-agent-{VERSION}.zip"]
    stage = staged(tmp_path, data)
    payload = signed_auth(data, key)
    approval = authorize_staged(stage, payload, pem(key), now=999)
    assert approval.name == f"ota-{TID}.approved.json"
    assert authorize_staged(stage, payload, pem(key), now=999) == approval
    actual, raw, sig, marker = load_approved_staged(
        tmp_path, PC, VERSION, pem(key), now=1000)
    assert actual.read_bytes() == data
    assert len(sig) == 64 and marker == approval
    assert json.loads(raw)["version"] == VERSION


@pytest.mark.parametrize("overrides", [
    {"device_id": "pc_2"}, {"transfer_id": "b" * 32}, {"protocol": 1},
    {"protocol": True}, {"other": "unsafe"}, {"manifest_b64": "%INVALID"},
    {"signature_b64": "eA=="}, {"signature_b64": "a" * 500},
])
def test_invalid_auth_never_promotes_quarantined_zip(tmp_path, overrides):
    key = Ed25519PrivateKey.generate()
    data = b"x" * 1024
    stage = staged(tmp_path, data)
    with pytest.raises(OtaTrustError):
        authorize_staged(stage, signed_auth(data, key, **overrides),
                         pem(key), now=999)
    assert not list(tmp_path.glob("*.approved.json"))
    assert stage.staged.read_bytes() == data


def test_wrong_signer_and_validly_signed_wrong_sha_never_authorize(tmp_path):
    key, wrong = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    data = b"real-release"
    stage = staged(tmp_path, data)
    with pytest.raises(OtaTrustError):
        authorize_staged(stage, signed_auth(data, wrong), pem(key), now=999)
    with pytest.raises(OtaTrustError, match="does not match"):
        authorize_staged(stage, signed_auth(b"other-release", key), pem(key), now=999)
    assert not list(tmp_path.glob("*.approved.json"))


def test_authenticated_marker_is_not_proof_after_file_tampering(tmp_path):
    key = Ed25519PrivateKey.generate()
    data = b"trusted-release"
    stage = staged(tmp_path, data)
    authorize_staged(stage, signed_auth(data, key), pem(key), now=999)
    stage.staged.write_bytes(b"evil-but-same-len")
    with pytest.raises(OtaTrustError):
        load_approved_staged(tmp_path, PC, VERSION, pem(key), now=1000)


def test_marker_expires_and_denies_wrong_pc_or_version(tmp_path):
    key = Ed25519PrivateKey.generate()
    data = b"ok"
    stage = staged(tmp_path, data)
    authorize_staged(stage, signed_auth(data, key), pem(key), now=999)
    for device, version, time in [
        ("pc_2", VERSION, 1000), (PC, "2.0.1", 1000),
        (PC, VERSION, 1600),
    ]:
        with pytest.raises(OtaTrustError):
            load_approved_staged(tmp_path, device, version, pem(key), now=time)


def test_real_transaction_consumes_authenticated_mqtt_zip_and_rolls_back_on_failure(tmp_path):
    from updater_fakes import Env, signed_release
    env = Env(tmp_path)
    env.data.joinpath("device_id").write_text(PC)
    key = env.key
    data = signed_release(key, VERSION)[f"windows-agent-{VERSION}.zip"]
    staging = env.data / "ota-staging"
    staging.mkdir()
    stage = staged(staging, data)
    authorize_staged(stage, signed_auth(data, key), pem(key), now=999)
    cfg_path = env.data / "updater.json"
    cfg = json.loads(cfg_path.read_text()) | {
        "mqtt_install_enabled": True,
        "authenticode_thumbprint": "A" * 40,
    }
    cfg_path.write_text(json.dumps(cfg))
    env.request(VERSION)
    seen = []
    assert env.updater(authenticode=lambda path, thumb:
                       seen.append((Path(path).name, thumb)) or True).run() == "success"
    env.assert_settled(VERSION, "success")
    assert env.downloads == []
    assert seen == [("SmartHouseGamingControl.exe", "A" * 40)]
    assert not list(staging.glob("*.approved.json"))
    assert not list(staging.glob("*.staged"))


def test_trusted_mqtt_mode_fails_closed_without_package_or_authenticode(tmp_path):
    from updater_fakes import Env
    env = Env(tmp_path)
    env.data.joinpath("device_id").write_text(PC)
    cfg = json.loads((env.data / "updater.json").read_text())
    cfg.update({"mqtt_install_enabled": True, "authenticode_thumbprint": "A" * 40})
    (env.data / "updater.json").write_text(json.dumps(cfg))
    env.request(VERSION)
    assert env.updater().run() == "failed"
    env.assert_settled("1.0.0", "failed")
    assert env.service.calls == []
    assert env.downloads == []



def test_pinned_bootstrap_refuses_unsigned_updater_configuration(tmp_path):
    from gaming_control.agent import pinned_ota_key
    key = Ed25519PrivateKey.generate()
    conf = tmp_path / "config.yaml"
    conf.write_text("mqtt: {}\n")
    (tmp_path / "ota-staging").mkdir()
    opts = {"update": {"enabled": True, "mqtt_staging_enabled": True,
                       "mqtt_install_enabled": True}}
    path = tmp_path / "updater.json"
    path.write_text(json.dumps({"mqtt_install_enabled": True,
                                "public_key_pem": pem(key).decode()}))
    with pytest.raises(ValueError, match="Authenticode"):
        pinned_ota_key(conf, opts)
    path.write_text(json.dumps({"mqtt_install_enabled": True,
                                "public_key_pem": pem(key).decode(),
                                "authenticode_thumbprint": "A" * 40}))
    # CI's non-Windows pure-input path exercises the out-of-band pin check;
    # Windows itself also checks the real signed updater executable/task.
    import os
    if os.name != "nt":
        assert pinned_ota_key(conf, opts) == pem(key).decode()
    (tmp_path / "ota-staging").rmdir()
    with pytest.raises(ValueError, match="staging"):
        pinned_ota_key(conf, opts)


def test_signed_ota_crash_after_commit_recovers_and_cleans_quarantine(tmp_path):
    from updater_fakes import Env, SimulatedCrash, signed_release
    env = Env(tmp_path)
    env.data.joinpath("device_id").write_text(PC)
    data = signed_release(env.key, VERSION)[f"windows-agent-{VERSION}.zip"]
    stage_dir = env.data / "ota-staging"
    stage_dir.mkdir()
    stage = staged(stage_dir, data)
    authorize_staged(stage, signed_auth(data, env.key), pem(env.key), now=999)
    marker = stage_dir / f"ota-{TID}.approved.json"
    cfg = json.loads((env.data / "updater.json").read_text()) | {
        "mqtt_install_enabled": True, "authenticode_thumbprint": "A" * 40,
    }
    (env.data / "updater.json").write_text(json.dumps(cfg))
    env.request(VERSION)
    env.crash_at = "journal:committed"
    with pytest.raises(SimulatedCrash):
        env.updater(authenticode=lambda *_: True).run()
    assert marker.exists()
    env.crash_at = None
    env.updater(authenticode=lambda *_: True).run()
    env.assert_settled(VERSION, "success")
    assert not marker.exists()
    assert not stage.staged.exists()
    assert not env.journal_path.exists()



def test_mqtt_v2_auth_route_accepts_only_finished_pinned_release(tmp_path):
    """A stage ACK without signed/authenticated receipt cannot authorize Install."""
    from gaming_control.ota_mqtt import OtaMqttReceiver
    key = Ed25519PrivateKey.generate()
    root = f"SmartHouse/Gaming/{PC}"
    receiver = OtaMqttReceiver(root, PC, tmp_path, public_key=pem(key))
    message = signed_auth(b"trusted-bytes", key)
    assert root + "/ota/auth" in receiver.topics
    assert receiver.handle(root + "/ota/auth", message, now=999) is None
    receiver.active = staged(tmp_path, b"trusted-bytes")
    accepted = json.loads(receiver.handle(root + "/ota/auth", message, now=999))
    assert accepted["status"] == "authenticated"
    assert accepted["transfer_id"] == TID
    assert receiver.handle(root + "/ota/auth", message, now=999) is not None
    assert (tmp_path / f"ota-{TID}.approved.json").is_file()
    wrong_key = Ed25519PrivateKey.generate()
    rejected = json.loads(receiver.handle(
        root + "/ota/auth", signed_auth(b"trusted-bytes", wrong_key), now=999))
    assert rejected["status"] == "rejected"
    assert rejected["device_id"] == PC


def test_v1_receiver_never_subscribes_or_acknowledges_signed_auth(tmp_path):
    from gaming_control.ota_mqtt import OtaMqttReceiver
    key = Ed25519PrivateKey.generate()
    root = f"SmartHouse/Gaming/{PC}"
    receiver = OtaMqttReceiver(root, PC, tmp_path)
    assert root + "/ota/auth" not in receiver.topics
    receiver.active = staged(tmp_path, b"safe")
    assert receiver.handle(
        root + "/ota/auth", signed_auth(b"safe", key), now=999) is None
    assert not list(tmp_path.glob("*.approved.json"))


def test_approval_refuses_second_parallel_receipt_and_symlinks(tmp_path):
    key = Ed25519PrivateKey.generate()
    content = b"sign only exactly these bytes"
    receiver = staged(tmp_path, content)
    foreign = tmp_path / ("ota-" + "e" * 32 + ".approved.json")
    foreign.write_text("{}")
    with pytest.raises(OtaTrustError, match="Another"):
        authorize_staged(receiver, signed_auth(content, key), pem(key), now=999)
    foreign.unlink()
    marker = authorize_staged(receiver, signed_auth(content, key), pem(key), now=999)
    archive = receiver.staged
    archive.unlink()
    archive.symlink_to(marker)
    with pytest.raises(OtaTrustError, match="archive missing"):
        load_approved_staged(tmp_path, PC, VERSION, pem(key), now=1000)


def test_agent_defaults_to_normal_telemetry_when_ota_bootstrap_missing(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from gaming_control import agent
    config = {"device": {"id": PC, "name": "PC"},
              "mqtt": {"host": "localhost"},
              "update": {"enabled": True, "mqtt_staging_enabled": True,
                         "mqtt_install_enabled": True}}
    mock = Mock()
    monkeypatch.setattr(agent, "Bridge", mock)
    def missing(*_args):
        raise ValueError("No trusted updater task")
    monkeypatch.setattr(agent, "pinned_ota_key", missing)
    result = agent._build_mqtt_bridge(tmp_path / "config.yaml", config)
    assert result is mock.return_value
    safe = mock.call_args.args[0]
    assert safe["update"]["mqtt_install_enabled"] is False
    assert safe["update"]["mqtt_staging_enabled"] is False
    assert config["update"]["mqtt_install_enabled"] is True  # source unchanged
    mock.reset_mock()
    safe_config = config | {"update": {}}
    agent._build_mqtt_bridge(tmp_path / "config.yaml", safe_config)
    mock.assert_called_once_with(safe_config)


def test_bootstrap_requires_update_flags_and_protected_provisioning(tmp_path):
    from gaming_control.agent import pinned_ota_key
    conf = tmp_path / "config.yaml"
    conf.write_text("mqtt: {}\n")
    disabled = {"update": {"mqtt_install_enabled": True,
                           "mqtt_staging_enabled": False, "enabled": True}}
    with pytest.raises(ValueError, match="requires explicitly"):
        pinned_ota_key(conf, disabled)
    (tmp_path / "ota-staging").mkdir()
    enabled = {"update": {"mqtt_install_enabled": True,
                          "mqtt_staging_enabled": True, "enabled": True}}
    with pytest.raises(ValueError, match="updater"):
        pinned_ota_key(conf, enabled)
    (tmp_path / "updater.json").write_text(json.dumps(
        {"mqtt_install_enabled": False, "public_key_pem": "not a key"}))
    with pytest.raises(ValueError, match="not enabled"):
        pinned_ota_key(conf, enabled)
