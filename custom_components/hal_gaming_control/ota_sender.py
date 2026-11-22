"""Pure HA-side builder for a bounded, device-scoped MQTT OTA byte stream.

This has NO MQTT subscription or publisher, UI control or install action.
Only a release independently authenticated by the Windows updater can be
installed. A content digest is an integrity check, not an authorizing signature.
"""
import hashlib
import json
import math
from pathlib import Path
import re

CHUNK_SIZE = 64 * 1024
MAX_PACKAGE = 200 * 1024 * 1024
_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z", re.ASCII)
_HEX = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\Z")


def _valid_id(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


class PackageFrames:
    """A fixed source ZIP is read incrementally; no whole-file buffering."""

    def __init__(self, path, *, device_id, version, transfer_id, expires_at):
        if (not _valid_id(device_id, _ID) or not _valid_id(transfer_id, _HEX)
                or not _valid_id(version, _VERSION)
                or type(expires_at) is not int or expires_at <= 0):
            raise ValueError("Invalid OTA sender identity")
        self.path = Path(path)
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError("OTA archive must be a regular file")
        self.size = self.path.stat().st_size
        if not 0 < self.size <= MAX_PACKAGE:
            raise ValueError("OTA package size invalid")
        self.device_id, self.version = device_id, version
        self.transfer_id, self.expires_at = transfer_id, expires_at
        self.digest = hashlib.sha256()
        with self.path.open("rb") as stream:
            while True:
                block = stream.read(CHUNK_SIZE)
                if not block:
                    break
                self.digest.update(block)
        self.sha256 = self.digest.hexdigest()

    @property
    def chunk_count(self):
        return math.ceil(self.size / CHUNK_SIZE)

    def offer(self):
        return json.dumps({
            "protocol": 1, "device_id": self.device_id,
            "transfer_id": self.transfer_id, "version": self.version,
            "size": self.size, "sha256": self.sha256,
            "chunk_size": CHUNK_SIZE, "expires_at": self.expires_at,
        }, separators=(",", ":"))

    def frames(self):
        """Read each packet once; never silently accept a changed source file."""
        sha = hashlib.sha256()
        size = 0
        with self.path.open("rb") as stream:
            for index in range(self.chunk_count):
                expected = min(CHUNK_SIZE, self.size - size)
                data = stream.read(expected)
                if len(data) != expected:
                    raise ValueError("OTA source changed during transfer")
                sha.update(data)
                size += len(data)
                yield bytes.fromhex(self.transfer_id) + index.to_bytes(4, "big") + data
            if stream.read(1) or sha.hexdigest() != self.sha256:
                raise ValueError("OTA source changed during transfer")

    def finish(self):
        return json.dumps({
            "protocol": 1, "device_id": self.device_id,
            "transfer_id": self.transfer_id,
        }, separators=(",", ":"))
