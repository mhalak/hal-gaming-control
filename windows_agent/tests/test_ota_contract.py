"""Contract test: HA package frame builder interoperates with Windows sink."""
import importlib.util
import json
from pathlib import Path

import pytest

from gaming_control.ota_staging import StageReceiver

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "custom_components/hal_gaming_control/ota_sender.py"


def sender_type():
    spec = importlib.util.spec_from_file_location("ota_sender_contract", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PackageFrames


def test_ha_sender_and_windows_receiver_transfer_all_bytes(tmp_path):
    payload = b"A" * 65536 + b"B" * 65536 + b"C" * 37
    source = tmp_path / "windows-agent.zip"
    source.write_bytes(payload)
    sender = sender_type()(source, device_id="pc_1", version="0.2.9",
                           transfer_id="f" * 32, expires_at=120)
    protected = tmp_path / "admin_only"
    protected.mkdir()
    receiver = StageReceiver(protected, "pc_1")
    receiver.start(sender.offer(), now=10)
    for index, frame in enumerate(sender.frames(), start=1):
        assert receiver.receive(frame, now=11) == index
        # Duplicate QoS1 redelivery does not write bytes twice.
        assert receiver.receive(frame, now=11) == index
    staged = receiver.finish(sender.finish(), now=12)
    assert staged.read_bytes() == payload


def test_ha_sender_corrupted_chunk_never_promotes(tmp_path):
    payload = b"SafeToStage" * 100
    source = tmp_path / "package.zip"
    source.write_bytes(payload)
    sender = sender_type()(source, device_id="pc_1", version="0.2.9",
                           transfer_id="f" * 32, expires_at=120)
    root = tmp_path / "protected"
    root.mkdir()
    receiver = StageReceiver(root, "pc_1")
    receiver.start(sender.offer(), now=10)
    frame = next(sender.frames())
    receiver.receive(frame[:20] + b"X" + frame[21:], now=11)
    with pytest.raises(ValueError, match="SHA-256"):
        receiver.finish(sender.finish(), now=12)
    assert not list(root.glob("*.staged"))
    receiver.abort()
    assert not list(root.iterdir())


def test_foreign_receiver_must_reject_ha_offer(tmp_path):
    sender_type_ = sender_type()
    source = tmp_path / "package.zip"
    source.write_bytes(b"abc")
    sender = sender_type_(source, device_id="pc_1", version="0.2.9",
                          transfer_id="f" * 32, expires_at=120)
    receiver = StageReceiver(tmp_path, "pc_2")
    with pytest.raises(ValueError):
        receiver.start(sender.offer(), now=10)
    assert list(tmp_path.glob("*.part")) == []
