"""Targeted MQTT termination must require a validated HA-tracked foreground."""
import json

import pytest

from custom_components.hal_gaming_control.targeted_protocol import (
    parse_offer, offer_matches_raw,
)

DEVICE = "pc1"
RAW = {"version": 2, "device_id": DEVICE, "epoch": "a" * 32,
       "sequence": 31, "observed_at": 100.0, "state": "foreground",
       "process": "RobloxPlayerBeta.exe", "signature": None}
OFFER = {"version": 1, "device_id": DEVICE, "epoch": "a" * 32,
         "sequence": 31, "observed_at": 100.0,
         "process": "RobloxPlayerBeta.exe", "signature": None,
         "token": "b" * 32}
TOPIC = "SmartHouse/Gaming/pc1/state/terminate_offer"


def decode(offer=OFFER, *, topic=TOPIC, retained=False, now=101.0):
    return parse_offer(topic, json.dumps(offer), DEVICE, retained=retained, now=now)


def test_fresh_offer_is_opaque_and_matches_only_tracked_raw_identity():
    offer = decode()
    assert offer == OFFER
    assert offer_matches_raw(offer, RAW, now=102, offered_at=101,
                             tracked={json.dumps(["robloxplayerbeta.exe", None],
                                                 separators=(",", ":"))})
    assert not offer_matches_raw(offer, RAW, now=105.1, offered_at=101,
                                 tracked=set())
    assert not offer_matches_raw(offer, RAW, now=102, offered_at=101,
                                 tracked=set())
    for changes in (
        {"epoch": "f" * 32}, {"sequence": 32},
        {"process": "explorer.exe"}, {"state": "unknown"},
        {"observed_at": 101},
    ):
        assert not offer_matches_raw(offer, RAW | changes, now=102,
                                     offered_at=101, tracked={
                                         json.dumps(["robloxplayerbeta.exe", None],
                                                    separators=(",", ":"))})


@pytest.mark.parametrize("changes", [
    {"device_id": "pc2"}, {"version": True}, {"version": 2},
    {"token": "bad"}, {"process": "C:/Windows/explorer.exe"},
    {"sequence": True}, {"sequence": 0}, {"epoch": "invalid"},
    {"observed_at": 20}, {"observed_at": 110},
    {"signature": {"kind": "java_class", "value": "x.y"}},
    {"pid": 410}, {"path": "private"},
])
def test_reject_malformed_or_foreign_offer(changes):
    with pytest.raises(ValueError):
        decode(OFFER | changes)


def test_reject_retained_duplicate_oversized_and_other_device_topics():
    for raw, topic, retained in (
        (json.dumps(OFFER), TOPIC, True),
        (json.dumps(OFFER), "SmartHouse/Gaming/pc2/state/terminate_offer", False),
        (json.dumps(OFFER) + "x", TOPIC, False),
        (json.dumps(OFFER).replace('"version": 1,', '"version": 1, "version": 1,'), TOPIC, False),
        ("x" * 1025, TOPIC, False),
    ):
        with pytest.raises(ValueError):
            parse_offer(topic, raw, DEVICE, retained=retained, now=101)


def test_ambiguous_java_offer_rejected_without_signature():
    with pytest.raises(ValueError):
        decode(OFFER | {"process": "javaw.exe"})
