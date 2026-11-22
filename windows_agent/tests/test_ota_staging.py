"""TDD: MQTT OTA transfer stages bytes but never authorizes execution (#166).

These tests intentionally exercise the receiver with untrusted, adversarial
offer and chunk payloads. A SHA-256 match is NOT a release signature.
"""
import hashlib
import json

import pytest

from gaming_control.ota_staging import (
    CHUNK_SIZE, MAX_PACKAGE, StageReceiver, encode_chunk, parse_offer,
)

DEVICE = "pc_1"
TID = "a" * 32


def offer(data=b"test", **changes):
    return {
        "protocol": 1, "device_id": DEVICE, "transfer_id": TID,
        "version": "0.2.9", "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "chunk_size": CHUNK_SIZE, "expires_at": 120,
    } | changes


def test_signed_release_is_not_implied_by_sha256(tmp_path):
    receiver = StageReceiver(tmp_path, DEVICE)
    payload = b"not even a ZIP, only arbitrary bytes"
    receiver.start(json.dumps(offer(payload)), now=10)
    assert receiver.receive(encode_chunk(TID, 0, payload), now=11) == 1
    path = receiver.finish(json.dumps({"protocol": 1, "device_id": DEVICE,
                                       "transfer_id": TID}), now=12)
    assert path.read_bytes() == payload
    assert path.suffix == ".staged"
    assert "verified" not in str(path)
    # The transport never starts a service or invokes an updater.
    assert list(tmp_path.iterdir()) == [path]


def test_many_chunks_and_idempotent_last_chunk_only(tmp_path):
    data = b"R" * CHUNK_SIZE + b"S" * CHUNK_SIZE + b"T" * 43
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer(data)), now=3)
    assert receiver.receive(encode_chunk(TID, 0, data[:CHUNK_SIZE]), now=4) == 1
    assert receiver.receive(encode_chunk(TID, 0, data[:CHUNK_SIZE]), now=4) == 1
    assert receiver.receive(encode_chunk(TID, 1, data[CHUNK_SIZE:2*CHUNK_SIZE]), now=5) == 2
    assert receiver.receive(encode_chunk(TID, 2, data[2*CHUNK_SIZE:]), now=6) == 3
    path = receiver.finish(json.dumps({"protocol": 1, "device_id": DEVICE,
                                       "transfer_id": TID}), now=7)
    assert path.read_bytes() == data
    assert receiver.completed is True


@pytest.mark.parametrize("change", [
    {"protocol": True}, {"protocol": 2}, {"device_id": "pc_2"},
    {"transfer_id": "../config.yaml"}, {"transfer_id": "A"*32},
    {"version": "0.2"}, {"version": "v0.2.9"},
    {"size": True}, {"size": 0}, {"size": MAX_PACKAGE + 1},
    {"sha256": "x"*64}, {"sha256": "A"*64},
    {"chunk_size": 2}, {"expires_at": True},
    {"expires_at": 10}, {"expires_at": 1000}, {"path": "C:/Windows/system32"},
])
def test_offer_never_accepts_extra_unsafe_or_expired_fields(change):
    with pytest.raises(ValueError):
        parse_offer(json.dumps(offer() | change), DEVICE, now=10)


@pytest.mark.parametrize("payload", [
    "{}", "[]", "{", "null", "x" * 1025,
    '{"protocol":1,"protocol":1}', b"\xff\xfe",
])
def test_offer_rejects_ambiguous_invalid_and_oversized_payload(payload):
    with pytest.raises(ValueError):
        parse_offer(payload, DEVICE, now=10)


def test_missing_reordered_foreign_or_changed_chunks_rejected(tmp_path):
    data = b"A" * CHUNK_SIZE + b"B" * 3
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer(data)), now=10)
    with pytest.raises(ValueError):
        receiver.receive(encode_chunk(TID, 1, data[CHUNK_SIZE:]), now=11)
    with pytest.raises(ValueError):
        receiver.receive(encode_chunk("b"*32, 0, data[:CHUNK_SIZE]), now=11)
    with pytest.raises(ValueError):
        receiver.receive(encode_chunk(TID, 0, b"A"*2), now=11)
    assert receiver.receive(encode_chunk(TID, 0, data[:CHUNK_SIZE]), now=11) == 1
    with pytest.raises(ValueError):
        receiver.receive(encode_chunk(TID, 0, b"B"*CHUNK_SIZE), now=11)
    with pytest.raises(ValueError):
        receiver.receive(encode_chunk(TID, 2, b"B"*3), now=11)
    with pytest.raises(ValueError):
        receiver.receive(encode_chunk(TID, 1, b"B"*4), now=11)
    assert receiver.receive(encode_chunk(TID, 1, data[CHUNK_SIZE:]), now=11) == 2


def test_malformed_binary_packet_and_size_limit(tmp_path):
    data = b"Z" * 7
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer(data)), now=10)
    for frame in (b"", b"\x00"*5, b"x" * (CHUNK_SIZE + 21),
                  bytes.fromhex(TID) + (0).to_bytes(4, "big"), encode_chunk(TID, 0, b"x"*8)):
        with pytest.raises(ValueError):
            receiver.receive(frame, now=10)
    assert receiver.receive(encode_chunk(TID, 0, data), now=11) == 1


def test_wrong_sha_does_not_promote_staged_file(tmp_path):
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer(b"A" * 3)), now=10)
    receiver.receive(encode_chunk(TID, 0, b"B" * 3), now=11)
    with pytest.raises(ValueError, match="SHA-256"):
        receiver.finish(json.dumps({"protocol": 1, "device_id": DEVICE,
                                    "transfer_id": TID}), now=12)
    assert not list(tmp_path.glob("*.staged"))
    receiver.abort()


def test_no_promotion_until_all_bytes_arrive(tmp_path):
    data = b"a" * (CHUNK_SIZE + 1)
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer(data)), now=10)
    receiver.receive(encode_chunk(TID, 0, data[:CHUNK_SIZE]), now=11)
    with pytest.raises(ValueError):
        receiver.finish(json.dumps({"protocol": 1, "device_id": DEVICE,
                                    "transfer_id": TID}), now=12)
    receiver.abort()


def test_finish_rejects_wrong_device_transfer_and_extra_fields(tmp_path):
    data = b"abcd"
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer(data)), now=10)
    receiver.receive(encode_chunk(TID, 0, data), now=11)
    for finish in (
        {"protocol": 1, "device_id": "pc_2", "transfer_id": TID},
        {"protocol": 1, "device_id": DEVICE, "transfer_id": "b"*32},
        {"protocol": 1, "device_id": DEVICE, "transfer_id": TID, "cmd": "run"},
    ):
        with pytest.raises(ValueError):
            receiver.finish(json.dumps(finish), now=12)


def test_offer_expiration_and_no_reuse_existing_staging_file(tmp_path):
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer()), now=10)
    with pytest.raises(ValueError, match="expired"):
        receiver.receive(encode_chunk(TID, 0, b"test"), now=120)
    receiver.abort()
    (tmp_path / f"ota-{TID}.staged").write_bytes(b"existing")
    with pytest.raises((FileExistsError, ValueError)):
        receiver.start(json.dumps(offer()), now=10)
    assert (tmp_path / f"ota-{TID}.staged").read_bytes() == b"existing"


def test_invalid_device_or_missing_root_is_never_created(tmp_path):
    with pytest.raises(ValueError):
        StageReceiver(tmp_path, "../other")
    with pytest.raises(ValueError):
        StageReceiver(tmp_path / "missing", DEVICE)
    assert not (tmp_path / "missing").exists()


def test_disallow_second_concurrent_start_and_safe_abort(tmp_path):
    receiver = StageReceiver(tmp_path, DEVICE)
    receiver.start(json.dumps(offer()), now=10)
    with pytest.raises(ValueError):
        receiver.start(json.dumps(offer(b"other", transfer_id="b"*32)), now=11)
    receiver.abort()
    assert not list(tmp_path.iterdir())
    receiver.abort()
