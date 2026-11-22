"""Resolve MQTT identity exclusively from the live Windows computer name.

BREAKING: the legacy YAML device section and persisted ProgramData/device_id
cannot select a device identity. The hostname is the sole source for both
MQTT routing identity and the published discovery name. Renaming Windows
requires re-enrollment and device-scoped broker ACL changes in HA.
"""

import re
import socket

# The current MQTT/HA v3 protocol permits ASCII word characters and hyphens.
# Fail closed rather than publish a different, silently sanitized identity.
_WINDOWS_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\\Z", flags=re.ASCII)


def windows_computer_name(*, computer_name=None):
    """Read the OS hostname; refuse values unsafe for the MQTT topic contract."""
    name = socket.gethostname() if computer_name is None else computer_name
    if not isinstance(name, str) or _WINDOWS_NAME.fullmatch(name) is None:
        raise ValueError("Invalid Windows computer name for MQTT identity")
    return name


def resolve_identity(config, config_path, *, computer_name=None):
    """Inject a runtime-only device descriptor, never read/write an ID file.

    config_path is retained for existing caller compatibility; it is not used.
    Configured IDs/names are no longer supported, even on upgraded installs.
    """
    if not isinstance(config, dict):
        raise ValueError("Invalid agent configuration")
    if "device" in config:
        raise ValueError("Remove obsolete device section; Windows computer name is mandatory")
    name = windows_computer_name(computer_name=computer_name)
    return {**config, "device": {"id": name, "name": name}}
