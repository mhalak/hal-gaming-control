"""Pinned-signature authorization for a quarantined MQTT OTA ZIP.

This is NOT an installer. A successful receipt lets the separately provisioned
SYSTEM updater consider a staged artifact after independently repeating every
cryptographic check. Never trust an MQTT-supplied path or public key.
"""
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_ENVELOPE = 8192
MAX_MANIFEST = 4096
MAX_PACKAGE = 200 * 1024 * 1024
MAX_AUTH_AGE = 600
ID = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\Z")
AUTH_KEYS = {"protocol", "device_id", "transfer_id", "manifest_b64", "signature_b64"}
MANIFEST_KEYS = {"version", "filename", "size", "sha256"}


class OtaTrustError(ValueError):
    """Fail-closed signed-release preflight failure."""


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise OtaTrustError("Duplicate signed OTA metadata field")
        result[name] = value
    return result


def _read_json(data, limit, keys):
    if not isinstance(data, (bytes, str)) or not 0 < len(data) <= limit:
        raise OtaTrustError("Invalid signed OTA message size")
    try:
        result = json.loads(data, object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise OtaTrustError("Invalid signed OTA JSON") from exc
    if not isinstance(result, dict) or result.keys() != keys:
        raise OtaTrustError("Unexpected signed OTA fields")
    return result


def _decode(encoded, limit):
    if not isinstance(encoded, str) or len(encoded) > (limit + 2) * 2:
        raise OtaTrustError("Invalid signed OTA base64")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise OtaTrustError("Invalid signed OTA base64") from exc
    if not 0 < len(raw) <= limit:
        raise OtaTrustError("Signed OTA field exceeds limit")
    return raw


def verify_signed_offer(payload, offer, device_id, public_key):
    """Verify source, device, exact offer hash/size and immutable artifact name."""
    envelope = _read_json(payload, MAX_ENVELOPE, AUTH_KEYS)
    if (type(envelope["protocol"]) is not int or envelope["protocol"] != 2
            or envelope["device_id"] != device_id
            or envelope["transfer_id"] != offer["transfer_id"]
            or not ID.fullmatch(offer["transfer_id"])):
        raise OtaTrustError("Signed OTA transfer/device mismatch")
    raw = _decode(envelope["manifest_b64"], MAX_MANIFEST)
    signature = _decode(envelope["signature_b64"], 64)
    if len(signature) != 64:
        raise OtaTrustError("Invalid Ed25519 signature length")
    try:
        key = serialization.load_pem_public_key(
            public_key.encode("ascii") if isinstance(public_key, str) else public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise OtaTrustError("Pinned Windows key is not Ed25519")
        key.verify(signature, raw)
    except (OtaTrustError, ValueError, TypeError) as exc:
        raise OtaTrustError("Untrusted Ed25519 release key") from exc
    except Exception as exc:
        raise OtaTrustError("Signed OTA signature verification failed") from exc
    manifest = _read_json(raw, MAX_MANIFEST, MANIFEST_KEYS)
    version = manifest["version"]
    if (not isinstance(version, str) or not VERSION.fullmatch(version)
            or version != offer["version"]
            or manifest["filename"] != f"windows-agent-{version}.zip"
            or type(manifest["size"]) is not int
            or manifest["size"] != offer["size"]
            or not 0 < manifest["size"] <= MAX_PACKAGE
            or not isinstance(manifest["sha256"], str)
            or not SHA.fullmatch(manifest["sha256"])
            or manifest["sha256"] != offer["sha256"]):
        raise OtaTrustError("Signed release does not match exact received ZIP")
    return envelope, manifest


def authorize_staged(stage, payload, public_key, *, now=None):
    """Persist a device-scoped signed receipt; never extract or run the ZIP.

    Repeated identical auth is idempotent; a different reauthorization for
    the same transfer is refused. Both marker and ZIP stay inside the
    provisioned protected ProgramData staging directory.
    """
    now = time.time() if now is None else now
    if (type(now) not in (int, float) or not 0 <= now < 2**53
            or not stage.completed or stage.offer is None
            or stage.staged is None):
        raise OtaTrustError("No completed OTA stage to authenticate")
    if now > stage.offer["expires_at"] + 30:
        raise OtaTrustError("Signed OTA authorization expired")
    root = Path(stage.root)
    if not root.is_dir() or root.is_symlink():
        raise OtaTrustError("Unprotected or missing OTA staging directory")
    envelope, manifest = verify_signed_offer(
        payload, stage.offer, stage.device_id, public_key)
    transfer_id = stage.offer["transfer_id"]
    staged = root / f"ota-{transfer_id}.staged"
    marker = root / f"ota-{transfer_id}.approved.json"
    if (staged != stage.staged or not staged.is_file()
            or staged.is_symlink() or staged.stat().st_size != manifest["size"]):
        raise OtaTrustError("Signed ZIP is not present in protected quarantine")
    # StageReceiver verified the streaming digest at FINISH. SYSTEM updater
    # performs a fresh digest and verifies this signature a second time.
    record = {
        "protocol": 2, "device_id": stage.device_id,
        "transfer_id": transfer_id, "version": manifest["version"],
        "manifest_b64": envelope["manifest_b64"],
        "signature_b64": envelope["signature_b64"],
        "approved_at": int(now),
    }
    raw = json.dumps(record, separators=(",", ":"), sort_keys=True)
    if marker.exists() or marker.is_symlink():
        try:
            existing = marker.read_text(encoding="utf-8")
            if existing != raw or marker.is_symlink():
                raise OtaTrustError("Conflicting signed OTA approval")
        except OSError as exc:
            raise OtaTrustError("Signed OTA approval inaccessible") from exc
    else:
        if any(root.glob("ota-*.approved.json")):
            raise OtaTrustError("Another signed OTA approval exists")
        with marker.open("x", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    return marker


def load_approved_staged(root, device_id, version, public_key, *, now=None):
    """SYSTEM updater reads one authenticated candidate, never a remote path.

    Returns (archive, signed_manifest, signature, marker). A subsequent
    independent hash check and Authenticode verification are mandatory.
    """
    now = time.time() if now is None else now
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OtaTrustError("OTA staging root unavailable")
    files = list(root.glob("ota-*.approved.json"))
    if len(files) != 1:
        raise OtaTrustError("Exactly one signed OTA approval required")
    marker = files[0]
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > MAX_ENVELOPE:
        raise OtaTrustError("Untrusted OTA approval marker")
    receipt = _read_json(
        marker.read_bytes(), MAX_ENVELOPE,
        {"protocol", "device_id", "transfer_id", "version",
         "manifest_b64", "signature_b64", "approved_at"})
    transfer_id = receipt["transfer_id"]
    if (type(receipt["protocol"]) is not int or receipt["protocol"] != 2
            or not isinstance(transfer_id, str) or not ID.fullmatch(transfer_id)
            or receipt["device_id"] != device_id or receipt["version"] != version
            or type(receipt["approved_at"]) is not int
            or not receipt["approved_at"] <= now <= receipt["approved_at"] + MAX_AUTH_AGE):
        raise OtaTrustError("Signed OTA approval is stale or wrong-device")
    archive = root / f"ota-{transfer_id}.staged"
    if not archive.is_file() or archive.is_symlink():
        raise OtaTrustError("Signed OTA archive missing")
    raw = base64.b64decode(receipt["manifest_b64"], validate=True)
    signature = base64.b64decode(receipt["signature_b64"], validate=True)
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    offer = {"transfer_id": transfer_id, "version": version,
             "size": archive.stat().st_size, "sha256": digest}
    verify_signed_offer(json.dumps({
        "protocol": 2, "device_id": device_id, "transfer_id": transfer_id,
        "manifest_b64": receipt["manifest_b64"],
        "signature_b64": receipt["signature_b64"]}).encode("utf-8"),
        offer, device_id, public_key)
    return archive, raw, signature, marker
