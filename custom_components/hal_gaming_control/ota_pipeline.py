"""HA-side signed-release -> MQTT stage-only OTA orchestration (#166).

This is an internal component helper, not an HA service, install command or
public update action. A 'staged_unverified' receipt MUST NOT be treated as an
installed version. Windows must separately authenticate the signed release,
check Authenticode and complete its durable updater transaction before install.
"""
import asyncio
from pathlib import Path

from .ota_release import SignedReleaseCache
from .ota_transport import HaOtaTransport
from .update_protocol import version_tuple


class OtaPreflightError(ValueError):
    """Safe refusal to stage untrusted, mismatched or ineligible release."""


def _stage_capable(device_id, online, remote_update, ota_protocol):
    return (isinstance(device_id, str) and bool(device_id)
            and online is True and remote_update is True
            and type(ota_protocol) is int and ota_protocol == 1)


def _source_configured(base_url, pinned_public_key):
    return (isinstance(base_url, str) and bool(base_url)
            and isinstance(pinned_public_key, (str, bytes))
            and bool(pinned_public_key))


def require_candidate(*, device_id, installed, approved, version, online,
                      remote_update, ota_protocol, base_url, pinned_public_key):
    """Only a newer, fixed-catalog release for a live stage-capable PC."""
    if not _stage_capable(device_id, online, remote_update, ota_protocol):
        raise OtaPreflightError("Windows PC is not online and explicitly OTA-capable")
    if not isinstance(version, str) or version != approved:
        raise OtaPreflightError("Only the fixed approved catalog release may be staged")
    try:
        target, current = version_tuple(version), version_tuple(installed)
    except (TypeError, ValueError) as exc:
        raise OtaPreflightError("Invalid current or approved release version") from exc
    if target <= current:
        raise OtaPreflightError("The approved release is not newer")
    if not _source_configured(base_url, pinned_public_key):
        raise OtaPreflightError("Release source and out-of-band pinned key are required")


class OtaStagingPipeline:
    """Composes the signed HA cache with stop-and-wait stage-only MQTT.

    Never publishes command/update or promotes staged bytes into installed
    status. The future caller must additionally establish HA admin authority;
    currently no callable HA service or UI invokes this pipeline.
    """

    def __init__(self, hass, private_cache_directory, *, cache=None, transport=None):
        self._hass = hass
        self._cache = cache or SignedReleaseCache(hass, Path(private_cache_directory))
        self._transport = transport or HaOtaTransport(hass)
        self._lock = asyncio.Lock()

    async def async_stage_approved(self, *, device_id, installed, approved,
                                   version, online, remote_update, ota_protocol,
                                   base_url, pinned_public_key, on_progress=None,
                                   signed_handoff=False):
        require_candidate(
            device_id=device_id, installed=installed, approved=approved,
            version=version, online=online, remote_update=remote_update,
            ota_protocol=ota_protocol, base_url=base_url,
            pinned_public_key=pinned_public_key)
        if signed_handoff and ota_protocol != 2:
            raise OtaPreflightError("Signed Windows OTA handoff requires v2 capability")
        if self._lock.locked():
            raise OtaPreflightError("OTA staging already running for this entity")
        async with self._lock:
            archive = await self._cache.async_prepare(
                base_url=base_url, version=version,
                pinned_public_key=pinned_public_key)
            if (archive.version != version or not archive.sha256
                    or type(archive.size) is not int or archive.size <= 0):
                raise OtaPreflightError("Cached release metadata mismatch")
            # The sender independently hashes the ZIP before sending. Passing
            # these values pins the byte stream to the SIGNED manifest, not
            # merely a sender-chosen digest.
            extra = ({"signed_manifest": archive.manifest,
                      "signed_signature": archive.signature}
                     if signed_handoff else {})
            receipt = await self._transport.async_stage_package(
                archive.path, device_id=device_id, version=version,
                expected_sha256=archive.sha256, expected_size=archive.size,
                on_progress=on_progress, **extra)
            if (not isinstance(receipt, dict)
                    or receipt.get("status") != ("authenticated_staged"
                        if signed_handoff else "staged_unverified")
                    or receipt.get("version") != version
                    or not isinstance(receipt.get("transfer_id"), str)):
                raise OtaPreflightError("MQTT receiver did not confirm staging")
            return receipt
