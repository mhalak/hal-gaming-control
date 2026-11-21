"""HA-only application enrollment, keyed by normalized executable identity.

Windows agents never receive or store these mappings. Existing config-entry
options are the durable source; display-name edits do not change stable keys.
"""
import json
import re

from .candidate_protocol import _valid_process, _valid_signature

MAX_APPS = 64
_RESERVED = frozenset(("idle", "unknown", "unavailable", "none"))


def identity_key(process, signature):
    """Stable key for a case-insensitive executable + safe launch signature."""
    if not _valid_process(process) or not _valid_signature(process, signature):
        raise ValueError("Invalid executable identity")
    if process.casefold() in ("java.exe", "javaw.exe") and signature is None:
        raise ValueError("Ambiguous Java runtime")
    discriminator = (signature["kind"], signature["value"].casefold()) if signature else None
    return json.dumps([process.casefold(), discriminator], separators=(",", ":"))


def _display_name(name):
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
            or name.strip().casefold() in _RESERVED
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
            or any(ch in name for ch in "<>{}")):
        raise ValueError("Invalid display name")
    return name.strip()


def load_apps(value):
    """Validate HA options; reject malformed or duplicated data (fail closed)."""
    if not isinstance(value, list) or len(value) > MAX_APPS:
        raise ValueError("Invalid tracked applications list")
    result = {}
    for row in value:
        if not isinstance(row, dict) or set(row) != {"process", "signature", "name"}:
            raise ValueError("Invalid tracked application")
        key = identity_key(row["process"], row["signature"])
        if key in result:
            raise ValueError("Duplicate application identity")
        result[key] = {"process": row["process"], "signature": row["signature"],
                       "name": _display_name(row["name"])}
    return result


def add_app(current, candidate, name):
    apps = load_apps(current)
    if not isinstance(candidate, dict):
        raise ValueError("No valid foreground candidate")
    key = identity_key(candidate["process"], candidate["signature"])
    if key in apps or len(apps) >= MAX_APPS:
        raise ValueError("Already tracked or application limit reached")
    apps[key] = {"process": candidate["process"],
                 "signature": candidate["signature"],
                 "name": _display_name(name)}
    return list(apps.values())


def rename_app(current, key, name):
    apps = load_apps(current)
    if key not in apps:
        raise ValueError("Application is no longer tracked")
    apps[key] = dict(apps[key], name=_display_name(name))
    return list(apps.values())


def remove_app(current, key):
    apps = load_apps(current)
    if key not in apps:
        raise ValueError("Application is no longer tracked")
    del apps[key]
    return list(apps.values())


def normalized_name(current, process, signature):
    """HA's future single Active game mapper; None means not tracked."""
    try:
        key = identity_key(process, signature)
        return load_apps(current).get(key, {}).get("name")
    except ValueError:
        return None
