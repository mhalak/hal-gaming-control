"""Strict wire validation for administrative update requests."""
import json
import re
import uuid
from urllib.parse import urlsplit

VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")
ACTIVE = {"downloading", "verifying", "stopping", "installing", "starting", "rollback"}
TERMINAL = {"success", "failed", "rolled_back", "failed_recovery_required"}

def version_tuple(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError("Invalid version")
    return tuple(map(int, value.split(".")))

def catalog_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Invalid URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Expected fixed HTTPS catalog URL")
    return value

def catalog_version(payload):
    data = json.loads(payload)
    if not isinstance(data, dict) or set(data) != {"version"}:
        raise ValueError("Invalid catalog")
    version_tuple(data["version"])
    return data["version"]

def make_request(installed, approved, now):
    if version_tuple(approved) <= version_tuple(installed):
        raise ValueError("Not an upgrade")
    return {"version": approved, "request_id": str(uuid.uuid4()), "expires_at": int(now) + 120}

def parse_status(payload):
    if len(payload) > 2048:
        raise ValueError("Status too large")
    data = json.loads(payload)
    if not isinstance(data, dict) or data.get("status") not in ACTIVE | TERMINAL:
        raise ValueError("Invalid status")
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
        raise ValueError("Invalid request ID")
    version_tuple(data.get("version"))
    if type(data.get("timestamp")) is not int:
        raise ValueError("Invalid timestamp")
    return data
