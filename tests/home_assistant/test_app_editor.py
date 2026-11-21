"""Single-screen editor preserves stable identities and rejects forged additions."""
import pytest

from custom_components.smarthouse_gaming.app_editor import (
    CandidateChanged, apply_app_editor, editor_choices, editor_rows, raw_label,
)
from custom_components.smarthouse_gaming.app_registry import identity_key

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
    edited = apply_app_editor(baseline, rows, ROBLOX, ROBLOX)
    assert edited == [
        {"process": "javaw.exe", "signature": JAVA["signature"],
         "name": "Minecraft Java"},
        {"process": "RobloxPlayerBeta.exe", "signature": None, "name": "Roblox"},
    ]
    assert apply_app_editor(edited, [editor_rows(edited)[1]], None, None) == [
        edited[1]]


def test_can_rename_when_no_fresh_candidate_exists():
    initial = [{"process": "RobloxPlayerBeta.exe", "signature": None,
                "name": "Roblox"}]
    assert apply_app_editor(initial, [
        {"name": "Roblox Classic", "detected": "RobloxPlayerBeta.exe"}],
        None, None)[0]["name"] == "Roblox Classic"


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
        apply_app_editor([], bad, ROBLOX, ROBLOX)


@pytest.mark.parametrize("changed", [
    None,
    {**ROBLOX, "token": "c" * 32},
    {**ROBLOX, "process": "chrome.exe"},
])
def test_new_app_must_match_fresh_candidate_even_if_list_is_editable(changed):
    with pytest.raises(CandidateChanged):
        apply_app_editor(
            [], [{"name": "Roblox", "detected": "RobloxPlayerBeta.exe"}],
            ROBLOX, changed)


def test_candidate_java_without_signature_cannot_be_added():
    vague = {"process": "javaw.exe", "signature": None, "token": "c" * 32}
    assert editor_choices([], vague) == {}
    with pytest.raises(ValueError):
        apply_app_editor([], [{"name": "Minecraft", "detected": "javaw.exe"}],
                         vague, vague)


def test_already_registered_candidate_is_not_added_twice():
    initial = [{"process": "RobloxPlayerBeta.exe", "signature": None,
                "name": "Roblox"}]
    choices = editor_choices(initial, ROBLOX)
    assert list(choices) == ["RobloxPlayerBeta.exe"]
    with pytest.raises(ValueError):
        apply_app_editor(initial, editor_rows(initial) + editor_rows(initial),
                         ROBLOX, ROBLOX)
