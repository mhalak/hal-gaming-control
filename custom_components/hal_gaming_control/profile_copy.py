"""Copy portable HA policy without transferring device-local state."""
from copy import deepcopy
from datetime import time

from .app_registry import load_apps
from .const import DEFAULTS

# Explicit ownership: defaults and additional persistent settings are portable;
# unlimited is a live override, not a profile setting. Unknown keys stay local.
PROFILE_DEFAULTS = {
    key: value for key, value in DEFAULTS.items() if key != "unlimited"
} | {"tracked_apps": [], "update_catalog_url": "",
     "ota_release_base_url": "", "ota_signer_public_key": ""}
INHERITED_FIELDS = ("weekend_schedule_start", "weekend_schedule_end")
TRUST_FIELDS = ("update_catalog_url", "ota_release_base_url", "ota_signer_public_key")


def validate_update_settings(catalog, base, public_key, enabled):
    """Share the same trust validation with the native update settings editor."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from .update_protocol import catalog_url
    from .ota_release import release_url

    if not all(isinstance(value, str) for value in (catalog, base, public_key)):
        raise ValueError("Invalid update configuration")
    if catalog:
        catalog_url(catalog)
    if base:
        release_url(base, "windows-agent-0.0.0.json")
    if public_key:
        if len(public_key) > 8192:
            raise ValueError("Public signing key too large")
        key = serialization.load_pem_public_key(public_key.encode("ascii"))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Expected pinned Ed25519 public key")
    if enabled and not (catalog and base and public_key):
        raise ValueError("All trusted release details must be configured")


def copy_profile(source, target):
    """Return one validated replacement; neither input is mutated."""
    profile = {key: deepcopy(source.get(key, default))
               for key, default in PROFILE_DEFAULTS.items()}
    # Preserve inheritance, not just today's effective weekend value.
    for field in INHERITED_FIELDS:
        if field in source:
            profile[field] = deepcopy(source[field])

    for key in ("enabled", "schedule_enabled"):
        if type(profile[key]) is not bool:
            raise ValueError("Invalid policy switch")
    # Historical non-slider values remain valid for daily/weekly policies.
    for key in ("daily", "weekly"):
        if type(profile[key]) is not int or profile[key] < -1:
            raise ValueError("Invalid gaming budget")
    bonus = profile["weekend_bonus"]
    if type(bonus) is not int or not 0 <= bonus <= 600 or bonus % 10:
        raise ValueError("Invalid weekend bonus")
    for key in ("schedule_start", "schedule_end", *INHERITED_FIELDS):
        if key in profile:
            if not isinstance(profile[key], str):
                raise ValueError("Invalid schedule")
            clock = time.fromisoformat(profile[key])
            if clock.tzinfo is not None or clock.microsecond:
                raise ValueError("Invalid schedule")
    profile["tracked_apps"] = list(load_apps(profile["tracked_apps"]).values())
    per_game = profile["per_game"]
    if (not isinstance(per_game, dict)
            or any(not isinstance(key, str) or type(value) is not int or value < -1
                   for key, value in per_game.items())):
        raise ValueError("Invalid per-game policy")
    if not isinstance(profile["actions"], list):
        raise ValueError("Invalid legacy actions configuration")

    trust = tuple(profile[key] for key in TRUST_FIELDS)
    validate_update_settings(*trust, False)

    result = deepcopy(dict(target))
    for field in (*PROFILE_DEFAULTS, *INHERITED_FIELDS, "weekend_daily", "weekend_total"):
        result.pop(field, None)
    result.update(profile)
    # Never transplant consent or silently extend an existing consent to a
    # different catalog, distribution directory, or verification key.
    if target.get("ota_install_enabled") is True:
        result["ota_install_enabled"] = (
            all(trust) and trust == tuple(target.get(key, "") for key in TRUST_FIELDS))
    return result
