"""Pure HA-side OTA sender: no MQTT side effects and no install permission."""
import hashlib
import json

import pytest

from custom_components.hal_gaming_control.ota_sender import PackageFrames

TID = "b" * 32
DEVICE = "pc1"
SIZE = 64 * 1024


def test_sender_emits_scoped_offer_fixed_binary_blocks_and_finish(tmp_path):
    archive = tmp_path / "windows-agent-0.2.9.zip"
    data = b"A" * SIZE + b"B" * SIZE + b"C" * 7
    archive.write_bytes(data)
    sender = PackageFrames(archive, device_id=DEVICE, version="0.2.9",
                           transfer_id=TID, expires_at=120)
    offer = json.loads(sender.offer())
    assert set(offer) == {"protocol", "device_id", "transfer_id", "version",
                          "size", "sha256", "chunk_size", "expires_at"}
    assert offer["sha256"] == hashlib.sha256(data).hexdigest()
    assert offer["device_id"] == DEVICE and offer["size"] == len(data)
    assert sender.chunk_count == 3
    frames = list(sender.frames())
    assert len(frames) == 3
    assert [len(frame) for frame in frames] == [SIZE + 20, SIZE + 20, 27]
    for index, frame in enumerate(frames):
        assert frame[:16].hex() == TID
        assert int.from_bytes(frame[16:20], "big") == index
    assert b"".join(frame[20:] for frame in frames) == data
    assert json.loads(sender.finish()) == {
        "protocol": 1, "device_id": DEVICE, "transfer_id": TID}


def test_generator_checks_mutation_before_finish(tmp_path):
    path = tmp_path / "file.zip"
    path.write_bytes(b"a" * 100)
    sender = PackageFrames(path, device_id=DEVICE, version="0.2.9",
                           transfer_id=TID, expires_at=120)
    path.write_bytes(b"b" * 100)
    with pytest.raises(ValueError, match="changed"):
        list(sender.frames())


@pytest.mark.parametrize("bad", [
    {"device_id": "pc/other"}, {"transfer_id": "x"},
    {"version": "v0.2.9"}, {"expires_at": True},
    {"expires_at": -1}, {"version": "0.2"},
])
def test_sender_rejects_invalid_identity(tmp_path, bad):
    path = tmp_path / "file.zip"
    path.write_bytes(b"a")
    kw = dict(device_id=DEVICE, version="0.2.9", transfer_id=TID, expires_at=120) | bad
    with pytest.raises(ValueError):
        PackageFrames(path, **kw)


def test_sender_rejects_missing_dir_symlink_and_oversize(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    with pytest.raises(ValueError):
        PackageFrames(folder, device_id=DEVICE, version="0.2.9",
                      transfer_id=TID, expires_at=120)
    with pytest.raises(ValueError):
        PackageFrames(tmp_path / "missing", device_id=DEVICE, version="0.2.9",
                      transfer_id=TID, expires_at=120)
    real = tmp_path / "real.zip"
    real.write_bytes(b"hello")
    link = tmp_path / "link.zip"
    try:
        link.symlink_to(real)
    except (NotImplementedError, OSError):
        pass  # Windows CI may lack privilege to create symlinks.
    else:
        with pytest.raises(ValueError):
            PackageFrames(link, device_id=DEVICE, version="0.2.9",
                          transfer_id=TID, expires_at=120)


def test_zero_length_and_explicit_no_ota_network_io(tmp_path):
    path = tmp_path / "empty.zip"
    path.write_bytes(b"")
    with pytest.raises(ValueError):
        PackageFrames(path, device_id=DEVICE, version="0.2.9",
                      transfer_id=TID, expires_at=120)
