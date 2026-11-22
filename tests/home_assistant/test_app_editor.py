"""Single-screen editor preserves stable identities and rejects forged additions."""
import pytest

from custom_components.parental.app_editor import (
    apply_app_editor, editor_choices, editor_rows, raw_label,
)
from custom_components.parental.app_registry import identity_key

JAVA = {"process": "javaw.exe", "signature":
        {"kind": "java_class", "value": "net.minecraft.client.main.Main"},
        "token": "a" * 32}
ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None,
          "token": "b" * 32}


def test_raw_labels_include_actual_process_and_java_signature():
    assert raw_label(ROBLOX) == "RobloxPlayerBeta.exe"
    assert raw_label(JAVA) == (
        "javaw.exe — java_class: net.minecraft.client.main.Main")
    assert identity_key(JAVA["process"], JAVA["signature"])


def test_add_rename_remove_in_one_submit_and_preserve_process():
    baseline = [{**JAVA, "name": "Old Minecraft"}]
    baseline[0].pop("token")
    rows = editor_rows(baseline)
    assert rows[0]["name"] == "Old Minecraft"
    rows[0]["name"] = "Minecraft Java"
    rows.append({"name": "Roblox", "detected": raw_label(ROBLOX)})
    edited = apply_app_editor(baseline, rows, ROBLOX)
    assert edited == [
        {"process": "javaw.exe", "signature": JAVA["signature"],
         "name": "Minecraft Java"},
        {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"},
    ]
    assert apply_app_editor(edited, [editor_rows(edited)[1]], None) == [
        edited[1]]


def test_can_rename_when_no_fresh_candidate_exists():
    initial = [{"process": "RobloxPlayerBeta.exe", "signature": None,
                "name": "Roblox"}]
    assert apply_app_editor(initial, [
        {"name": "Roblox Classic", "detected": "RobloxPlayerBeta.exe"}],
        None)[0]["name"] == "Roblox Classic"


@pytest.mark.parametrize("bad", [
    [{"name": "Unknown", "detected": "sensitive.exe"}],
    [{"name": "Name", "detected": "javaw.exe"}],
    [{"name": "Roblox", "detected": "RobloxPlayerBeta.exe"},
     {"name": "Duplicate", "detected": "RobloxPlayerBeta.exe"}],
    [{"name": "", "detected": "RobloxPlayerBeta.exe"}],
    [{"name": "idle", "detected": "RobloxPlayerBeta.exe"}],
])
def test_rejects_unverified_duplicate_or_reserved_entries(bad):
    with pytest.raises(ValueError):
        apply_app_editor([], bad, ROBLOX)


@pytest.mark.parametrize("changed", [
    None,
    {**ROBLOX, "token": "c" * 32},
    {**ROBLOX, "process": "chrome.exe"},
])
def test_session_snapshot_remains_authorized_after_later_foreground_change(changed):
    # The changed current state has no bearing on the saved per-flow snapshot.
    captured = ROBLOX.copy()
    assert apply_app_editor(
        [], [{"name": "Roblox", "detected": "RobloxPlayerBeta.exe"}],
        captured) == [
        {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"}]
    assert changed != captured


def test_no_snapshot_cannot_create_unverified_application():
    with pytest.raises(ValueError):
        apply_app_editor([], [{"name": "Roblox", "detected": "RobloxPlayerBeta.exe"}],
                         None)


def test_candidate_java_without_signature_cannot_be_added():
    vague = {"process": "javaw.exe", "signature": None, "token": "c" * 32}
    assert editor_choices([], vague) == {}
    with pytest.raises(ValueError):
        apply_app_editor([], [{"name": "Minecraft", "detected": "javaw.exe"}],
                         vague)


def test_already_registered_candidate_is_not_added_twice():
    initial = [{"process": "RobloxPlayerBeta.exe", "signature": None,
                "name": "Roblox"}]
    choices = editor_choices(initial, ROBLOX)
    assert list(choices) == ["RobloxPlayerBeta.exe"]
    with pytest.raises(ValueError):
        apply_app_editor(initial, editor_rows(initial) + editor_rows(initial),
                         ROBLOX)
