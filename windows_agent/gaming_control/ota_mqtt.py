"""Explicitly provisioned MQTT OTA receiver: stages only, never installs.

The adapter has no arbitrary URL, shell command or installer call. A complete
SHA-256 staging result is UNTRUSTED until the separate pinned-signature
Windows updater validates a release independently.
"""
import json
from pathlib import Path
import time

from .ota_staging import StageReceiver, decode_chunk, parse_offer


class OtaMqttReceiver:
    """One in-memory, connection-bound stop-and-wait upload per Windows PC."""

    def __init__(self, root, device_id, staging_root):
        self.root = root
        self.device_id = device_id
        self.staging_root = Path(staging_root)
        # Fail at provisioning, not halfway through a transfer.
        StageReceiver(self.staging_root, self.device_id)
        self.topics = {
            f"{root}/ota/start", f"{root}/ota/chunk", f"{root}/ota/finish"}
        self.active = None

    def reset(self):
        """Discard incomplete data and prevent reconnect replay."""
        if self.active is not None:
            self.active.abort()
        self.active = None

    def _ack(self, active, status):
        """No local paths, request bodies or credentials in MQTT statuses."""
        offer = active.offer
        return json.dumps({
            "protocol": 1, "device_id": self.device_id,
            "transfer_id": offer["transfer_id"],
            "next_index": active.next_index, "status": status,
        }, separators=(",", ":"))

    def handle(self, topic, payload, *, now=None):
        """Return an optional non-retained ACK JSON; never executes the payload."""
        if topic not in self.topics:
            return None
        now = time.time() if now is None else now
        suffix = topic.rsplit("/", 1)[-1]
        if suffix == "start":
            return self._start(payload, now)
        if self.active is None:
            return None
        if suffix == "chunk":
            return self._chunk(payload, now)
        if suffix == "finish":
            return self._finish(payload, now)
        return None

    def _start(self, payload, now):
        if self.active is not None and not self.active.completed:
            if now < self.active.offer["expires_at"]:
                # Do not disclose the active transfer ID to invalid/foreign
                # reoffers. Only an identical live offer is idempotent.
                try:
                    current = parse_offer(payload, self.device_id, now=now)
                except ValueError:
                    return None
                return (self._ack(self.active, "receiving")
                        if current == self.active.offer else None)
            self.reset()  # Reclaim expired partial data before fresh start.
        candidate = StageReceiver(self.staging_root, self.device_id)
        try:
            candidate.start(payload, now=now)
        except (ValueError, FileExistsError, OSError):
            candidate.abort()
            return None
        self.active = candidate
        return self._ack(self.active, "receiving")

    def _chunk(self, payload, now):
        active = self.active
        try:
            transfer_id, _, _ = decode_chunk(payload)
        except ValueError:
            return None
        if transfer_id != active.offer["transfer_id"]:
            return None  # Never disclose active ID to a foreign upload.
        try:
            active.receive(payload, now=now)
        except (ValueError, OSError):
            # Never expose a byte sequence or a user-controlled filename.
            return self._ack(active, "receiving")
        return self._ack(active, "receiving")

    def _finish(self, payload, now):
        active = self.active
        try:
            active.finish(payload, now=now)
        except (ValueError, FileExistsError, OSError):
            result = self._ack(active, "rejected")
            self.reset()
            return result
        return self._ack(active, "staged")
