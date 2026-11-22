"""Synthetic, bounded, non-retained live candidate protocol."""
import json
import pytest

from custom_components.hal_gaming_control.candidate_protocol import parse_candidate


TOPIC = "SmartHouse/Gaming/pc1/state/foreground_candidate"
VALID = {"version": 1, "device_id": "pc1", "process": "Chrome.exe", "signature": None,
         "token": "a" * 32, "observed_at": 100}


def decode(value=VALID, *, topic=TOPIC, retained=False, now=102):
    return parse_candidate(topic, json.dumps(value), "pc1",
                           retained=retained, now=now)


def test_live_minimal_candidate_is_accepted():
    assert decode() == {"process": "Chrome.exe", "signature": None, "token": "a" * 32,
                        "observed_at": 100}


@pytest.mark.parametrize("bad", [
    VALID | {"device_id": "pc2"}, VALID | {"version": 2},
    VALID | {"version": True}, VALID | {"token": "short"},
    VALID | {"process": r"C:\\Private\\password.exe"},
    VALID | {"process": "secret\\n.exe"},
    VALID | {"process": "x" * 130 + ".exe"},
    VALID | {"process": "game.exe", "window_title": "private"},
    VALID | {"observed_at": float("nan")},
    VALID | {"observed_at": True},
])
def test_foreign_or_unsafe_fields_are_rejected(bad):
    with pytest.raises(ValueError):
        decode(bad)


@pytest.mark.parametrize("kwargs", [
    {"retained": True}, {"retained": None}, {"now": 108},
    {"now": 97}, {"topic": "SmartHouse/Gaming/pc2/state/foreground_candidate"},
    {"topic": "SmartHouse/Gaming/pc1/state/foreground_candidate/other"},
])
def test_stale_replayed_and_wrong_scope_rejected(kwargs):
    with pytest.raises(ValueError):
        decode(**kwargs)


def test_duplicate_json_fields_and_oversized_payload_rejected():
    raw = ('{"version":1,"version":1,"device_id":"pc1","process":"x.exe",'
           '"token":"' + "a" * 32 + '","observed_at":100}')
    with pytest.raises(ValueError):
        parse_candidate(TOPIC, raw, "pc1", retained=False, now=100)
    with pytest.raises(ValueError):
        parse_candidate(TOPIC, "x" * 1025, "pc1", retained=False, now=100)


def test_two_java_entry_points_have_distinct_safe_identifiers():
    minecraft = VALID | {
        "process": "javaw.exe",
        "signature": {"kind": "java_class",
                      "value": "net.minecraft.client.main.Main"},
    }
    other = VALID | {
        "process": "javaw.exe",
        "signature": {"kind": "java_class", "value": "org.example.other.Main"},
    }
    one, two = decode(minecraft), decode(other)
    assert one["process"] == two["process"]
    assert one["signature"] != two["signature"]


@pytest.mark.parametrize("signature", [
    {"kind": "java_class", "value": "Main"},  # no unique namespace
    {"kind": "java_class", "value": r"C:\\Private\\Main"},
    {"kind": "java_jar", "value": r"C:\\Private\\Minecraft.jar"},
    {"kind": "java_jar", "value": "sensitive personal.jar"},
    {"kind": "java_class", "value": "org.example.Main", "raw_args": "SECRET"},
    {"kind": "raw", "value": "--accessToken SECRET"},
    {"kind": "java_class", "value": "org.example.Main --accessToken SECRET"},
])
def test_private_or_ambiguous_java_signatures_rejected(signature):
    with pytest.raises(ValueError):
        decode(VALID | {"process": "javaw.exe", "signature": signature})


def test_non_java_executable_cannot_claim_java_signature():
    with pytest.raises(ValueError):
        decode(VALID | {"process": "chrome.exe",
                        "signature": {"kind": "java_class", "value": "org.example.Main"}})


def test_unhashable_signature_kind_is_rejected():
    with pytest.raises(ValueError):
        decode(VALID | {"process": "javaw.exe",
                        "signature": {"kind": [], "value": "org.example.Main"}})
