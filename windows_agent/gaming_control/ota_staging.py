"""Quarantined, bounded MQTT OTA package staging (transport only).

This module does NOT authenticate a release, unpack archives or install code.
The independent Windows updater must verify a pinned Ed25519 signature,
archive limits and Windows executable trust before any deployment.

No runtime MQTT subscriptions or HA controls are enabled by this module.
"""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re

CHUNK_SIZE = 64 * 1024
MAX_PACKAGE = 200 * 1024 * 1024
MAX_OFFER = 1024
HEADER_BYTES = 20
HEX_32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
HEX_64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
DEVICE = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z", re.ASCII)
VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\Z")
_OFFER_KEYS = frozenset(("protocol", "device_id", "transfer_id", "version",
                         "size", "sha256", "chunk_size", "expires_at"))
_FINISH_KEYS = frozenset(("protocol", "device_id", "transfer_id"))


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate OTA field")
        obj[key] = value
    return obj


def _json_object(payload, keys):
    if not isinstance(payload, (str, bytes)) or not 0 < len(payload) <= MAX_OFFER:
        raise ValueError("Invalid OTA JSON size")
    try:
        obj = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid OTA JSON") from exc
    if not isinstance(obj, dict) or obj.keys() != keys:
        raise ValueError("Invalid OTA JSON fields")
    return obj


def _valid_id(value, regex):
    return isinstance(value, str) and regex.fullmatch(value) is not None


def _valid_now(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def parse_offer(payload, device_id, *, now):
    """Validate a fixed, device-scoped, short-lived transfer declaration."""
    obj = _json_object(payload, _OFFER_KEYS)
    if (type(obj["protocol"]) is not int or obj["protocol"] != 1
            or not _valid_id(device_id, DEVICE) or obj["device_id"] != device_id
            or not _valid_id(obj["transfer_id"], HEX_32)
            or not _valid_id(obj["version"], VERSION)
            or type(obj["size"]) is not int
            or not 0 < obj["size"] <= MAX_PACKAGE
            or not _valid_id(obj["sha256"], HEX_64)
            or type(obj["chunk_size"]) is not int or obj["chunk_size"] != CHUNK_SIZE
            or type(obj["expires_at"]) is not int or not _valid_now(now)
            or not now < obj["expires_at"] <= now + 120):
        raise ValueError("Invalid or expired OTA offer")
    return obj


def parse_finish(payload, device_id, transfer_id):
    obj = _json_object(payload, _FINISH_KEYS)
    if (type(obj["protocol"]) is not int or obj["protocol"] != 1
            or obj["device_id"] != device_id
            or obj["transfer_id"] != transfer_id):
        raise ValueError("Foreign OTA finish")
    return obj


def encode_chunk(transfer_id, index, payload):
    """Binary MQTT frame: 16-byte transfer ID + 4-byte BE index + raw data."""
    if (not _valid_id(transfer_id, HEX_32)
            or type(index) is not int or not 0 <= index < 2**32
            or not isinstance(payload, bytes) or not 0 < len(payload) <= CHUNK_SIZE):
        raise ValueError("Invalid OTA chunk")
    return bytes.fromhex(transfer_id) + index.to_bytes(4, "big") + payload


def decode_chunk(frame):
    if (not isinstance(frame, bytes)
            or not HEADER_BYTES < len(frame) <= HEADER_BYTES + CHUNK_SIZE):
        raise ValueError("Invalid OTA frame size")
    transfer_id = frame[:16].hex()
    index = int.from_bytes(frame[16:20], "big")
    return transfer_id, index, frame[HEADER_BYTES:]


class StageReceiver:
    """Stop-and-wait sink, staging bytes only into a protected local directory.

    The *caller* must ensure root is Administrator/SYSTEM writable only. This
    pure transport deliberately does not create directories, authorize updates
    or preserve a transfer across a process restart (fail closed).
    """

    def __init__(self, root, device_id):
        self.root = Path(root)
        if not _valid_id(device_id, DEVICE):
            raise ValueError("Invalid device identifier")
        if not self.root.is_dir() or self.root.is_symlink():
            raise ValueError("Staging directory must already exist")
        self.device_id = device_id
        self.offer = None
        self.part = None
        self.staged = None
        self.file = None
        self.digest = None
        self.next_index = 0
        self.received = 0
        self.last_hash = None
        self.completed = False

    def start(self, payload, *, now):
        if self.offer is not None or self.completed:
            raise ValueError("OTA transfer already started")
        obj = parse_offer(payload, self.device_id, now=now)
        transfer_id = obj["transfer_id"]
        part = self.root / f"ota-{transfer_id}.part"
        staged = self.root / f"ota-{transfer_id}.staged"
        if staged.exists() or staged.is_symlink():
            raise FileExistsError("Staged transfer already exists")
        # Exclusive creation never truncates a previous/incomplete transaction.
        fd = part.open("xb")
        self.offer, self.part, self.staged, self.file = obj, part, staged, fd
        self.digest = hashlib.sha256()
        return obj

    def receive(self, frame, *, now):
        if self.offer is None or self.completed:
            raise ValueError("No live OTA transfer")
        if not _valid_now(now) or now >= self.offer["expires_at"]:
            raise ValueError("OTA offer expired")
        transfer_id, index, data = decode_chunk(frame)
        if transfer_id != self.offer["transfer_id"]:
            raise ValueError("Wrong OTA transfer")
        if index == self.next_index - 1 and self.last_hash is not None:
            if hmac.compare_digest(self.last_hash, hashlib.sha256(data).digest()):
                return self.next_index  # QoS 1 duplicate, safe to acknowledge.
            raise ValueError("Conflicting repeated OTA chunk")
        if index != self.next_index:
            raise ValueError("OTA chunk out of order")
        expected = min(CHUNK_SIZE, self.offer["size"] - self.received)
        if expected <= 0 or len(data) != expected:
            raise ValueError("Unexpected OTA chunk size")
        self.file.write(data)
        self.digest.update(data)
        self.received += len(data)
        self.next_index += 1
        self.last_hash = hashlib.sha256(data).digest()
        return self.next_index

    def finish(self, payload, *, now):
        if self.offer is None or self.completed:
            raise ValueError("No live OTA transfer")
        if not _valid_now(now) or now >= self.offer["expires_at"]:
            raise ValueError("OTA offer expired")
        parse_finish(payload, self.device_id, self.offer["transfer_id"])
        if self.received != self.offer["size"]:
            raise ValueError("OTA transfer incomplete")
        if not hmac.compare_digest(self.digest.hexdigest(), self.offer["sha256"]):
            raise ValueError("OTA SHA-256 mismatch")
        if self.staged.exists() or self.staged.is_symlink():
            raise FileExistsError("Staged transfer already exists")
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        self.file = None
        self.part.rename(self.staged)
        self.completed = True
        return self.staged

    def abort(self):
        if self.file is not None:
            self.file.close()
            self.file = None
        if not self.completed and self.part is not None:
            self.part.unlink(missing_ok=True)
        self.offer = None
        self.part = None
