"""Public, expiring, device-scoped v1 termination offers.

An offer is NOT authority to terminate by itself. It must match the last
verified non-retained raw v2 sample for an explicitly HA-tracked application.
"""
import json
import math
import re

from .app_registry import identity_key
from .candidate_protocol import _unique_object, _valid_process, _valid_signature
from .foreground_snapshot import MAX_SEQUENCE

OFFER_TTL = 4.0
_FIELDS = frozenset((
    "version", "device_id", "epoch", "sequence", "observed_at",
    "process", "signature", "token",
))


def parse_offer(topic, payload, device_id, *, retained, now):
    """Validate exact device, freshness, non-retained transport and safe fields."""
    if (retained is not False
            or topic != f"SmartHouse/Gaming/{device_id}/state/terminate_offer"
            or not isinstance(payload, (str, bytes))
            or not 0 < len(payload) <= 1024):
        raise ValueError("Invalid targeted offer transport")
    try:
        value = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid targeted offer JSON") from exc
    if (not isinstance(value, dict) or value.keys() != _FIELDS
            or type(value["version"]) is not int or value["version"] != 1
            or value["device_id"] != device_id
            or not isinstance(value["epoch"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", value["epoch"])
            or type(value["sequence"]) is not int
            or not 1 <= value["sequence"] <= MAX_SEQUENCE
            or type(value["observed_at"]) not in (int, float)
            or not math.isfinite(value["observed_at"])
            or type(now) not in (int, float) or not math.isfinite(now)
            or not -1 <= now - value["observed_at"] < OFFER_TTL
            or not _valid_process(value["process"])
            or not _valid_signature(value["process"], value["signature"])
            or not isinstance(value["token"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", value["token"])):
        raise ValueError("Invalid targeted offer identity")
    # Generic Java runtimes cannot be safely selected without a discriminator.
    identity_key(value["process"], value["signature"])
    return value


def offer_matches_raw(offer, raw, *, now, offered_at, tracked):
    """Only the *same* verified raw observation of a tracked app is actionable."""
    if (not isinstance(offer, dict) or not isinstance(raw, dict)
            or type(now) not in (int, float) or type(offered_at) not in (int, float)
            or not math.isfinite(now) or not math.isfinite(offered_at)
            or not 0 <= now - offered_at < OFFER_TTL
            or raw.get("state") != "foreground"):
        return False
    for key in ("device_id", "epoch", "sequence", "observed_at"):
        if raw.get(key) != offer.get(key):
            return False
    try:
        matched = (identity_key(raw["process"], raw["signature"])
                   == identity_key(offer["process"], offer["signature"]))
        return matched and identity_key(offer["process"], offer["signature"]) in tracked
    except (ValueError, KeyError, TypeError):
        return False
