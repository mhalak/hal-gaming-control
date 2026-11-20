"""Synthetic, bounded, non-retained live candidate protocol."""
import json
import pytest

from custom_components.smarthouse_gaming.candidate_protocol import parse_candidate


TOPIC = "SmartHouse/Gaming/pc1/state/foreground_candidate"
VALID = {"version": 1, "device_id": "pc1", "process": "Chrome.exe",
         "token": "a" * 32, "observed_at": 100}


def decode(value=VALID, *, topic=TOPIC, retained=False, now=102):
    return parse_candidate(topic, json.dumps(value), "pc1",
                           retained=retained, now=now)


def test_live_minimal_candidate_is_accepted():
    assert decode() == {"process": "Chrome.exe", "token": "a" * 32,
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
