"""HA-only Windows release cache: verify pinned Ed25519 manifest, then stage ZIP bytes.

Not connected to UpdateEntity or an HA service. A manifest signature authenticates
the archive metadata, NOT Windows Authenticode/executable trust or permission to
install; the Windows updater must independently verify all release evidence.
"""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientTimeout
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .ota_sender import CHUNK_SIZE, MAX_PACKAGE
from .update_protocol import version_tuple

MAX_MANIFEST = 4096
SIGNATURE_BYTES = 64
MAX_KEY = 8192
DOWNLOAD_TIMEOUT = 180
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MANIFEST_KEYS = frozenset(("version", "filename", "size", "sha256"))


class ReleaseCacheError(ValueError):
    """A candidate release is not a safely authenticated cached ZIP."""


@dataclass(frozen=True)
class SignedArchive:
    """Ed25519-manifest-authenticated archive; NOT Authenticode-validated."""

    path: Path
    version: str
    sha256: str
    size: int
    manifest: bytes
    signature: bytes


def _unique_object(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate signed release field")
        values[key] = value
    return values


def release_url(base, filename):
    """Only fixed artifact names from one operator-specified HTTPS directory."""
    parsed = urlsplit(base) if isinstance(base, str) else None
    if (parsed is None or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or len(base) > 2048 or not filename.startswith("windows-agent-")):
        raise ReleaseCacheError("Expected fixed HTTPS release directory")
    return base.rstrip("/") + "/" + filename


def verify_signed_manifest(manifest, signature, public_key_pem, version):
    """Match the canonical Windows updater's four-field signed JSON schema."""
    version_tuple(version)
    if (not isinstance(manifest, bytes) or not 0 < len(manifest) <= MAX_MANIFEST
            or not isinstance(signature, bytes) or len(signature) != SIGNATURE_BYTES
            or not isinstance(public_key_pem, (str, bytes))
            or not 0 < len(public_key_pem) <= MAX_KEY):
        raise ReleaseCacheError("Missing or oversized pinned release evidence")
    try:
        raw_key = public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem
        key = serialization.load_pem_public_key(raw_key)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Expected pinned Ed25519 key")
        key.verify(signature, manifest)
        obj = json.loads(manifest, object_pairs_hook=_unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (InvalidSignature, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ReleaseCacheError("Invalid pinned release signature or manifest") from exc
    expected = f"windows-agent-{version}.zip"
    if (not isinstance(obj, dict) or obj.keys() != _MANIFEST_KEYS
            or obj["version"] != version or obj["filename"] != expected
            or type(obj["size"]) is not int or not 0 < obj["size"] <= MAX_PACKAGE
            or not isinstance(obj["sha256"], str)
            or _DIGEST.fullmatch(obj["sha256"]) is None):
        raise ReleaseCacheError("Signed release metadata did not match requested version")
    return obj


def _secure_directory(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ReleaseCacheError("Release cache must be an ordinary directory")
    # The HA cache contains large binaries. On POSIX forbid shared writes/reads.
    if os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ReleaseCacheError("Release cache permissions must be private")


def _file_digest(path):
    if path.is_symlink() or not path.is_file():
        raise ReleaseCacheError("Cached artifact is not a regular file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest(), path.stat().st_size


def _new_private_file(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def _sync_close(handle):
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


class SignedReleaseCache:
    """Download immutable, signed-version ZIP into a private HA-owned cache.

    Future HA UpdateEntity wiring must validate administrator authorization,
    live device OTA capability, fixed approved version, and Windows updater
    readiness before using the result. This class has no MQTT or install side
    effects and never substitutes for Windows-side Authenticode checks.
    """

    def __init__(self, hass, directory, *, session=None):
        self.hass = hass
        self.root = Path(directory)
        self.session = session
        self.lock = asyncio.Lock()

    async def async_prepare(self, *, base_url, version, pinned_public_key):
        """Obtain .json/.sig then cache exactly the signed, SHA-256-matching ZIP."""
        version_tuple(version)
        async with self.lock:
            base = release_url(base_url, f"windows-agent-{version}.json")
            filename = f"windows-agent-{version}"
            session = self.session or async_get_clientsession(self.hass)
            try:
                manifest = await self._small(session, base, MAX_MANIFEST)
                signature = await self._small(
                    session, release_url(base_url, filename + ".sig"), SIGNATURE_BYTES)
                info = await asyncio.to_thread(
                    verify_signed_manifest, manifest, signature, pinned_public_key, version)
                await asyncio.to_thread(_secure_directory, self.root)
                path = self.root / f"{filename}-{info['sha256']}.zip"
                if path.exists() or path.is_symlink():
                    digest, size = await asyncio.to_thread(_file_digest, path)
                    if digest != info["sha256"] or size != info["size"]:
                        raise ReleaseCacheError("Existing cached artifact is corrupt")
                else:
                    await self._download(
                        session, release_url(base_url, filename + ".zip"), path, info)
                return SignedArchive(path, version, info["sha256"], info["size"],
                                     manifest, signature)
            except (ClientError, asyncio.TimeoutError, OSError) as exc:
                raise ReleaseCacheError("Release source or private cache unavailable") from exc

    async def _small(self, session, url, limit):
        async with session.get(
                url, allow_redirects=False, timeout=ClientTimeout(total=20)) as response:
            if response.status != 200:
                raise ReleaseCacheError("Release source returned non-success HTTP status")
            data = bytearray()
            async for block in response.content.iter_chunked(CHUNK_SIZE):
                data.extend(block)
                if len(data) > limit:
                    raise ReleaseCacheError("Signed release metadata exceeds size limit")
            return bytes(data)

    async def _download(self, session, url, target, info):
        temporary = self.root / (".ota-" + secrets.token_hex(16) + ".part")
        handle = await asyncio.to_thread(_new_private_file, temporary)
        digest = hashlib.sha256()
        size = 0
        try:
            async with session.get(
                    url, allow_redirects=False,
                    timeout=ClientTimeout(total=DOWNLOAD_TIMEOUT)) as response:
                if response.status != 200:
                    raise ReleaseCacheError("Release ZIP returned non-success HTTP status")
                async for block in response.content.iter_chunked(CHUNK_SIZE):
                    size += len(block)
                    if size > info["size"]:
                        raise ReleaseCacheError("Downloaded ZIP larger than signed size")
                    digest.update(block)
                    await asyncio.to_thread(handle.write, block)
            if size != info["size"] or digest.hexdigest() != info["sha256"]:
                raise ReleaseCacheError("Downloaded ZIP does not match signed digest")
            await asyncio.to_thread(_sync_close, handle)
            # Exclusive final commit: an existing file for this SHA is immutable.
            if target.exists() or target.is_symlink():
                raise ReleaseCacheError("Release cache destination already exists")
            # link() refuses an existing destination; never clobber an immutable cache.
            await asyncio.to_thread(os.link, temporary, target)
        finally:
            if not handle.closed:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
