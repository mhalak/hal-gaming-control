"""Verified Windows release cache contracts; network simulated, no devices touched."""
import hashlib
import json
import os
from pathlib import Path
import stat

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from custom_components.hal_gaming_control.ota_release import (
    MAX_PACKAGE, ReleaseCacheError, SignedReleaseCache,
    release_url, verify_signed_manifest,
)

BASE = "https://updates.example.invalid/windows/releases"
VERSION = "0.2.11"


class Response:
    def __init__(self, payload=b"", *, status=200):
        self.payload = payload
        self.status = status
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def iter_chunked(self, _size):
        # Real aiohttp sends bounded blocks; split here to exercise streaming.
        for i in range(0, len(self.payload), 16384):
            yield self.payload[i:i + 16384]


class FakeSession:
    def __init__(self, objects):
        self.objects = objects
        self.requested = []

    def get(self, url, *, timeout, allow_redirects):
        assert not allow_redirects
        assert timeout.total in (20, 180)
        self.requested.append(url)
        return self.objects.get(url, Response(status=404))


def bundle(*, version=VERSION, archive=None):
    key = Ed25519PrivateKey.generate()
    zip_bytes = archive if archive is not None else b"windows-agent" * 5500
    filename = f"windows-agent-{version}"
    manifest = json.dumps(
        {"version": version, "filename": filename + ".zip",
         "size": len(zip_bytes), "sha256": hashlib.sha256(zip_bytes).hexdigest()},
        sort_keys=True, separators=(",", ":")).encode()
    signature = key.sign(manifest)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    session = FakeSession({
        BASE + "/" + filename + ".json": Response(manifest),
        BASE + "/" + filename + ".sig": Response(signature),
        BASE + "/" + filename + ".zip": Response(zip_bytes),
    })
    return session, manifest, signature, public, zip_bytes


async def test_signed_manifest_and_cache_streaming_roundtrip(tmp_path):
    session, raw, sig, public, data = bundle()
    cache = SignedReleaseCache(None, tmp_path / "private-ota", session=session)
    prepared = await cache.async_prepare(
        base_url=BASE, version=VERSION, pinned_public_key=public)
    assert prepared.path.read_bytes() == data
    assert prepared.version == VERSION and prepared.size == len(data)
    assert prepared.sha256 == hashlib.sha256(data).hexdigest()
    assert prepared.manifest == raw and prepared.signature == sig
    assert prepared.path.name.startswith("windows-agent-0.2.11-")
    assert len(session.requested) == 3
    assert not list((tmp_path / "private-ota").glob("*.part"))
    if os.name == "posix":
        assert stat.S_IMODE(prepared.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(prepared.path.parent.stat().st_mode) == 0o700
    assert verify_signed_manifest(raw, sig, public, VERSION)["version"] == VERSION


async def test_identical_cache_reuse_still_revalidates_signed_manifest(tmp_path):
    session, _, _, public, data = bundle()
    cache = SignedReleaseCache(None, tmp_path / "cache", session=session)
    first = await cache.async_prepare(
        base_url=BASE, version=VERSION, pinned_public_key=public)
    url = BASE + f"/windows-agent-{VERSION}.zip"
    session.objects[url] = Response(b"untrusted different bytes")
    second = await cache.async_prepare(
        base_url=BASE, version=VERSION, pinned_public_key=public)
    assert second.path == first.path
    assert first.path.read_bytes() == data
    assert session.requested.count(url) == 1


@pytest.mark.parametrize("url", [
    "http://updates.example.invalid/releases",
    "https://name:password@updates.example.invalid/releases",
    "https://updates.example.invalid/releases?token=foo",
    "https://updates.example.invalid/releases#fragment",
    "https://",
    "x" * 2049,
])
def test_only_fixed_https_release_base_is_allowed(url):
    with pytest.raises(ReleaseCacheError):
        release_url(url, "windows-agent-0.2.11.zip")


async def test_wrong_pinned_key_and_tampered_signed_manifest_fail(tmp_path):
    session, raw, sig, public, _ = bundle()
    other = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(ReleaseCacheError, match="signature"):
        verify_signed_manifest(raw, sig, other, VERSION)
    with pytest.raises(ReleaseCacheError, match="signature"):
        verify_signed_manifest(raw + b" ", sig, public, VERSION)
    with pytest.raises(ReleaseCacheError, match="evidence"):
        verify_signed_manifest(raw, sig[:-1], public, VERSION)
    cache = SignedReleaseCache(None, tmp_path / "cache", session=session)
    with pytest.raises(ReleaseCacheError):
        await cache.async_prepare(
            base_url=BASE, version=VERSION, pinned_public_key=other)
    assert not (tmp_path / "cache").exists()
    assert session.requested == [
        BASE + f"/windows-agent-{VERSION}.json",
        BASE + f"/windows-agent-{VERSION}.sig"]


@pytest.mark.parametrize("payload", [
    {"version": "0.2.10"},
    {"filename": "../evil.zip"},
    {"size": 0},
    {"size": MAX_PACKAGE + 1},
    {"size": True},
    {"sha256": "not-a-hash"},
    {"extra": "ignored"},
])
def test_valid_signature_does_not_override_manifest_schema(payload):
    key = Ed25519PrivateKey.generate()
    _, base, _, _, data = bundle()
    obj = json.loads(base)
    obj.update(payload)
    raw = json.dumps(obj, sort_keys=True).encode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(ReleaseCacheError):
        verify_signed_manifest(raw, key.sign(raw), public, VERSION)


def test_signed_duplicate_json_fields_are_rejected():
    key = Ed25519PrivateKey.generate()
    _, raw, _, _, _ = bundle()
    malformed = raw[:-1] + b',"version":"0.2.11"}'
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(ReleaseCacheError, match="signature"):
        verify_signed_manifest(malformed, key.sign(malformed), public, VERSION)


async def test_zip_hash_or_size_mismatch_removes_partial_file(tmp_path):
    session, _, _, public, data = bundle()
    url = BASE + f"/windows-agent-{VERSION}.zip"
    session.objects[url] = Response(data + b"tamper")
    root = tmp_path / "cache"
    cache = SignedReleaseCache(None, root, session=session)
    with pytest.raises(ReleaseCacheError, match="larger"):
        await cache.async_prepare(base_url=BASE, version=VERSION, pinned_public_key=public)
    assert list(root.iterdir()) == []
    session.objects[url] = Response(data[:-2] + b"!!")
    with pytest.raises(ReleaseCacheError, match="digest"):
        await cache.async_prepare(base_url=BASE, version=VERSION, pinned_public_key=public)
    assert list(root.iterdir()) == []


async def test_corrupted_existing_cached_file_is_never_reused_or_overwritten(tmp_path):
    session, _, _, public, _ = bundle()
    cache = SignedReleaseCache(None, tmp_path / "cache", session=session)
    first = await cache.async_prepare(base_url=BASE, version=VERSION, pinned_public_key=public)
    first.path.write_bytes(b"changed")
    with pytest.raises(ReleaseCacheError, match="corrupt"):
        await cache.async_prepare(base_url=BASE, version=VERSION, pinned_public_key=public)
    assert first.path.read_bytes() == b"changed"


async def test_http_error_and_absent_artifacts_fail_without_creating_cache(tmp_path):
    session, _, _, public, _ = bundle()
    session.objects[BASE + f"/windows-agent-{VERSION}.json"] = Response(status=302)
    cache = SignedReleaseCache(None, tmp_path / "cache", session=session)
    with pytest.raises(ReleaseCacheError, match="non-success"):
        await cache.async_prepare(base_url=BASE, version=VERSION, pinned_public_key=public)
    assert not (tmp_path / "cache").exists()


async def test_reject_symlinked_cache_and_world_readable_cache(tmp_path):
    session, _, _, public, _ = bundle()
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "alias"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ReleaseCacheError, match="directory"):
        await SignedReleaseCache(None, link, session=session).async_prepare(
            base_url=BASE, version=VERSION, pinned_public_key=public)
    if os.name == "posix":
        real.chmod(0o755)
        with pytest.raises(ReleaseCacheError, match="permissions"):
            await SignedReleaseCache(None, real, session=session).async_prepare(
                base_url=BASE, version=VERSION, pinned_public_key=public)
