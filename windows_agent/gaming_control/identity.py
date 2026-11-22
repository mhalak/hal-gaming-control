"""Resolve stable per-install MQTT identity and the live Windows computer name.

The protected ProgramData directory is owned by the Windows installer. An
existing YAML device ID is authoritative on migration, but is also persisted so
users can later remove the legacy device section without re-enrolling in HA.
"""

import os
from pathlib import Path
import re
import socket
from uuid import uuid4


_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\\Z", flags=re.ASCII)
_ID_FILE = "device_id"


def _valid_id(value):
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError("Invalid device ID (expected 1-64 ASCII letters, numbers, _ or -)")
    return value


def _persisted_id(config_path, configured_id):
    path = Path(config_path).parent / _ID_FILE
    candidate = _valid_id(configured_id) if configured_id is not None else f"pc_{uuid4().hex}"
    try:
        # Exclusive create: never overwrite identity owned by a previous install.
        # ProgramData protections are established by install.ps1.
        with path.open("x", encoding="ascii") as stream:
            stream.write(candidate + "\\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass
    stored = _valid_id(path.read_text(encoding="ascii").strip())
    if configured_id is not None and stored != candidate:
        raise ValueError("Configured device ID conflicts with the persisted installation ID")
    return stored


def resolve_identity(config, config_path, *, computer_name=None):
    """Add stable ID and current hostname without modifying the source config.

    A legacy ID wins over generated identity; the previous hardcoded display
    name never wins over the Windows computer name. HA remains responsible for
    the user-customized friendly name.
    """
    if not isinstance(config, dict):
        raise ValueError("Invalid agent configuration")
    old_device = config.get("device") or {}
    if not isinstance(old_device, dict):
        raise ValueError("Invalid device configuration")
    name = socket.gethostname() if computer_name is None else computer_name
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 100
            or any(not ch.isprintable() for ch in name)):
        raise ValueError("Invalid Windows computer name")
    configured_id = old_device.get("id")
    if configured_id is not None:
        _valid_id(configured_id)
    device_id = _persisted_id(config_path, configured_id)
    return {**config, "device": {**old_device, "id": device_id, "name": name.strip()}}
