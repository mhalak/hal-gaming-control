"""HA MQTT OTA v1 sender: ACK-driven staging, NOT Windows installation.

This module has no user-facing service, no UpdateEntity install action, no
network download and no authorization to run a received Windows executable.
Only a future pinned-signature release pipeline may invoke this transport.
"""
import asyncio
from functools import partial
import json
import secrets
from time import monotonic, time

from homeassistant.components import mqtt

from .const import ROOT
from .ota_sender import PackageFrames

MAX_ACK = 1024
ACK_TIMEOUT = 3.0
RETRIES = 3
TRANSFER_TTL = 110
_ACK_FIELDS = {"protocol", "device_id", "transfer_id", "next_index", "status"}
_STATUSES = {"receiving", "staged", "rejected"}


class OtaTransferError(Exception):
    """The receiver did not confirm a complete, untrusted staged transfer."""


def _unique_object(pairs):
    out = {}
    for key, val in pairs:
        if key in out:
            raise ValueError("Duplicate OTA ACK field")
        out[key] = val
    return out


def parse_ack(payload, device_id, transfer_id, chunk_count):
    """Strictly correlate a non-retained ACK to one destination and transfer."""
    if not isinstance(payload, (bytes, str)) or not 0 < len(payload) <= MAX_ACK:
        raise ValueError("Invalid OTA ACK size")
    try:
        data = json.loads(payload, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Invalid OTA ACK JSON") from exc
    if (not isinstance(data, dict) or data.keys() != _ACK_FIELDS
            or type(data["protocol"]) is not int or data["protocol"] != 1
            or data["device_id"] != device_id or data["transfer_id"] != transfer_id
            or type(data["next_index"]) is not int
            or not 0 <= data["next_index"] <= chunk_count
            or type(data["status"]) is not str or data["status"] not in _STATUSES):
        raise ValueError("Invalid OTA ACK fields or identity")
    return data


def _next_frame(generator):
    """Avoid StopIteration escaping into an asyncio Future."""
    try:
        return next(generator)
    except StopIteration:
        return None


class _Transfer:
    def __init__(self, hass, package, *, ack_timeout, retries, on_progress):
        self.hass = hass
        self.package = package
        self.base = f"{ROOT}/{package.device_id}/ota"
        self.ack_timeout = ack_timeout
        self.retries = retries
        self.on_progress = on_progress
        self.queue = asyncio.Queue(maxsize=32)

    def _receive_ack(self, message):
        if getattr(message, "retain", False):
            return
        try:
            value = parse_ack(message.payload, self.package.device_id,
                              self.package.transfer_id, self.package.chunk_count)
        except ValueError:
            return
        if self.queue.full():
            self.queue.get_nowait()  # Bounded even under a duplicate ACK flood.
        self.queue.put_nowait(value)

    async def _publish(self, stage, payload):
        await mqtt.async_publish(self.hass, f"{self.base}/{stage}", payload,
                                 qos=1, retain=False)

    async def _confirmed(self, expected, status):
        deadline = monotonic() + self.ack_timeout
        while True:
            remaining = min(deadline - monotonic(), self.package.expires_at - time())
            if remaining <= 0:
                raise asyncio.TimeoutError()
            data = await asyncio.wait_for(self.queue.get(), timeout=remaining)
            if data["status"] == "rejected":
                raise OtaTransferError("Windows rejected the OTA staging transfer")
            if data["next_index"] > expected:
                raise OtaTransferError("Future OTA ACK index (protocol violation)")
            if data["next_index"] < expected:
                continue  # Delayed duplicate ACK from a previous block.
            if data["status"] == status:
                return
            if data["status"] == "staged" or status == "receiving":
                raise OtaTransferError("Unexpected OTA staging state")
            # A late receiving ACK is possible while waiting for staged.

    async def _step(self, stage, payload, expected, status, *, can_retry=True):
        attempts = self.retries + 1 if can_retry else 1
        for _ in range(attempts):
            if time() >= self.package.expires_at:
                raise OtaTransferError("OTA transfer expired")
            try:
                await self._publish(stage, payload)
                await self._confirmed(expected, status)
                return
            except asyncio.TimeoutError:
                continue
        if stage == "finish":
            # Windows v1 does not ACK a repeated finish idempotently: NEVER
            # retransmit FINISH, since its first attempt may have succeeded.
            raise OtaTransferError("OTA finish unconfirmed; verify receiver manually")
        raise OtaTransferError(f"OTA {stage} ACK timeout after {attempts} attempts")

    async def run(self):
        unsub = await mqtt.async_subscribe(self.hass, self.base + "/ack",
                                           self._receive_ack, qos=1)
        try:
            await self._step("start", self.package.offer(), 0, "receiving")
            frames = self.package.frames()
            for n in range(self.package.chunk_count):
                frame = await self.hass.async_add_executor_job(_next_frame, frames)
                if frame is None:
                    raise OtaTransferError("OTA source ended prematurely")
                await self._step("chunk", frame, n + 1, "receiving")
                if self.on_progress is not None:
                    self.on_progress(n + 1, self.package.chunk_count)
            # The sender verifies source checksum after the last yield.
            if await self.hass.async_add_executor_job(_next_frame, frames) is not None:
                raise OtaTransferError("OTA source unexpectedly grew")
            await self._step("finish", self.package.finish(),
                             self.package.chunk_count, "staged", can_retry=False)
            return {"transfer_id": self.package.transfer_id,
                    "version": self.package.version,
                    "chunks": self.package.chunk_count,
                    "status": "staged_unverified"}
        finally:
            unsub()


class HaOtaTransport:
    """HA-managed transfer engine, with one active session per PC.

    Callers must own the *approved signed package* release pipeline. This
    engine deliberately does not expose a service, update entity, or install
    command and does not attest the package's provenance.
    """

    def __init__(self, hass):
        self.hass = hass
        self._locks = {}

    async def async_stage_package(self, path, *, device_id, version,
                                  transfer_id=None, ack_timeout=ACK_TIMEOUT,
                                  retries=RETRIES, on_progress=None):
        if (type(ack_timeout) not in (float, int) or not 0 < ack_timeout <= 30
                or type(retries) is not int or not 0 <= retries <= 5):
            raise ValueError("Invalid OTA transport retry limits")
        lock = self._locks.setdefault(device_id, asyncio.Lock())
        if lock.locked():
            raise OtaTransferError("OTA transfer already active for device")
        async with lock:
            transfer_id = transfer_id or secrets.token_hex(16)
            # Hashing is O(package size): never block HA's event loop.
            package = await self.hass.async_add_executor_job(partial(
                PackageFrames, path, device_id=device_id, version=version,
                transfer_id=transfer_id, expires_at=int(time()) + TRANSFER_TTL))
            return await _Transfer(
                self.hass, package, ack_timeout=ack_timeout,
                retries=retries, on_progress=on_progress).run()
