"""Issue #4 HA-owned mapping, privacy and stable identity time accounting."""
import json
from datetime import datetime, timezone

import pytest

from custom_components.smarthouse_gaming.raw_foreground import (
    HAOwnedForeground, decode_raw_identity,
)

JAVA = {"process": "javaw.exe",
        "signature": {"kind": "java_class", "value": "net.minecraft.client.main.Main"},
        "name": "Minecraft"}
OTHER = {"process": "javaw.exe",
         "signature": {"kind": "java_class", "value": "org.example.other.Main"},
         "name": "Other Java"}
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}


def packet(ts, seq, *, device="pc1", state="foreground",
           process="javaw.exe", signature=None, epoch="a" * 32):
    if signature is None and process == "javaw.exe" and state == "foreground":
        signature = JAVA["signature"]
    if state != "foreground":
        process = signature = None
    return json.dumps({
        "version": 2, "device_id": device, "epoch": epoch, "sequence": seq,
        "observed_at": ts, "state": state, "process": process,
        "signature": signature,
    })


def receive(tracker, ts, seq, **kwargs):
    return tracker.observe(packet(ts, seq, **kwargs), retained=False,
                           wall_now=ts, monotonic_now=100000 + ts)


def weekly(tracker, ts):
    return tracker.totals(datetime.fromtimestamp(ts, timezone.utc))["weekly"]


def test_java_and_roblox_use_ha_names_not_agent_rules():
    tracker = HAOwnedForeground("pc1", [JAVA, OTHER, ROBLOX])
    assert receive(tracker, 100, 1)
    assert tracker.current(100100) == "Minecraft"
    assert receive(tracker, 102, 2)
    assert weekly(tracker, 103) == 2
    assert receive(tracker, 104, 3, process="javaw.exe",
                   signature=OTHER["signature"])
    assert tracker.current(100104) == "Other Java"
    assert receive(tracker, 106, 4, process="javaw.exe",
                   signature=OTHER["signature"])
    assert weekly(tracker, 108) == 4
    assert receive(tracker, 108, 5, process="RobloxPlayerBeta.exe")
    assert tracker.current(100108) == "Roblox"
    assert receive(tracker, 110, 6, process="RobloxPlayerBeta.exe")
    assert weekly(tracker, 112) == 6


def test_unconfigured_app_is_idle_for_tracking_not_chargeable():
    tracker = HAOwnedForeground("pc1", [JAVA])
    assert receive(tracker, 100, 1, process="chrome.exe")
    assert tracker.current(100100) == "idle"
    assert receive(tracker, 102, 2, process="chrome.exe")
    assert weekly(tracker, 104) == 0
    assert receive(tracker, 104, 3)
    assert tracker.current(100104) == "Minecraft"
    assert receive(tracker, 106, 4)
    assert weekly(tracker, 108) == 2


def test_empty_configuration_not_automatically_imported_from_windows():
    tracker = HAOwnedForeground("pc1", [])
    assert receive(tracker, 100, 1)
    assert tracker.current(100100) == "idle"
    assert receive(tracker, 102, 2)
    assert weekly(tracker, 103) == 0


def test_rename_persists_segments_under_stable_raw_identity():
    old = HAOwnedForeground("pc1", [JAVA])
    assert receive(old, 100, 1)
    assert receive(old, 102, 2)
    segments = old.export_segments()
    assert segments and segments[0][2] != "Minecraft"
    renamed = HAOwnedForeground("pc1", [JAVA | {"name": "Minecraft Java"}],
                                intervals=segments)
    # A restart cannot bridge a previous live observation.
    assert receive(renamed, 104, 3)
    assert weekly(renamed, 105) == 2
    assert renamed.current(100104) == "Minecraft Java"
    assert receive(renamed, 106, 4)
    assert weekly(renamed, 107) == 4


def test_unknown_unmappable_java_and_disconnect_never_look_idle():
    tracker = HAOwnedForeground("pc1", [JAVA])
    assert receive(tracker, 100, 1)
    ambiguous = json.loads(packet(102, 2))
    ambiguous["signature"] = None
    assert tracker.observe(json.dumps(ambiguous), retained=False,
                           wall_now=102, monotonic_now=100102)
    assert tracker.current(100102) is None
    assert weekly(tracker, 103) == 0
    assert receive(tracker, 104, 3, state="idle")
    assert tracker.current(100104) == "idle"
    tracker.invalidate()
    assert tracker.current(100104) is None


@pytest.mark.parametrize("mod", [
    {"version": 1}, {"version": True}, {"device_id": "pc2"},
    {"process": "C:/private/game.exe"}, {"process": "x" * 300 + ".exe"},
    {"state": "idle"}, {"state": "playing"},
    {"sequence": True}, {"sequence": 0}, {"epoch": "invalid"},
    {"observed_at": float("nan")},
])
def test_reject_bad_protocol(mod):
    data = json.loads(packet(100, 1)) | mod
    if mod.get("state") == "idle":
        data["process"] = "javaw.exe"
    with pytest.raises(ValueError):
        decode_raw_identity(json.dumps(data), "pc1")


def test_reject_replay_stale_retained_and_cross_device():
    tracker = HAOwnedForeground("pc1", [JAVA])
    assert not tracker.observe(packet(100, 1), retained=True,
                               wall_now=100, monotonic_now=100100)
    assert receive(tracker, 102, 2)
    assert not receive(tracker, 104, 2)
    assert weekly(tracker, 105) == 0
    assert not tracker.observe(packet(105, 3, device="pc2"), retained=False,
                               wall_now=105, monotonic_now=100105)
    assert not tracker.observe(packet(100, 4), retained=False,
                               wall_now=115, monotonic_now=100115)
    assert receive(tracker, 116, 5)
    assert receive(tracker, 118, 6)
    assert weekly(tracker, 119) == 2


def test_unsafe_java_arguments_not_accepted():
    data = json.loads(packet(100, 1))
    data["signature"] = {"kind": "java_jar", "value": "C:/secret.jar"}
    with pytest.raises(ValueError):
        decode_raw_identity(json.dumps(data), "pc1")


def test_duplicate_field_and_oversized_payload_fail_closed():
    tracker = HAOwnedForeground("pc1", [JAVA])
    duplicate = packet(100, 1).replace('"version": 2,', '"version": 2, "version": 2,')
    assert not tracker.observe(duplicate, retained=False,
                               wall_now=100, monotonic_now=100100)
    with pytest.raises(ValueError):
        decode_raw_identity("x" * 4097, "pc1")
