"""HA-only tracked application model — no Windows configuration side effects."""
import pytest

from custom_components.parental.app_registry import (
    add_app, identity_key, load_apps, normalized_name, remove_app, rename_app,
)


ROBLOX = {"process": "RobloxPlayerBeta.exe", "signature": None}
MINECRAFT = {"process": "javaw.exe",
             "signature": {"kind": "java_class", "value": "net.minecraft.client.main.Main"}}
OTHER_JAVA = {"process": "javaw.exe",
              "signature": {"kind": "java_class", "value": "org.example.other.Main"}}


def test_add_rename_remove_and_identity_are_stable():
    apps = add_app([], ROBLOX, "Roblox")
    apps = add_app(apps, MINECRAFT, "Minecraft Java")
    apps = add_app(apps, OTHER_JAVA, "Java Editor")
    key = identity_key("JAVAW.EXE", {"kind": "java_class",
                                     "value": "NET.MINECRAFT.CLIENT.MAIN.MAIN"})
    assert key in load_apps(apps)
    assert normalized_name(apps, "javaw.exe", MINECRAFT["signature"]) == "Minecraft Java"
    renamed = rename_app(apps, key, "Minecraft: Java Edition")
    assert identity_key("javaw.exe", MINECRAFT["signature"]) == key
    assert normalized_name(renamed, "javaw.exe", MINECRAFT["signature"]) == "Minecraft: Java Edition"
    assert normalized_name(renamed, "javaw.exe", OTHER_JAVA["signature"]) == "Java Editor"
    assert normalized_name(renamed, "Minecraft.Windows.exe", None) is None
    removed = remove_app(renamed, key)
    assert len(removed) == 2
    assert key not in load_apps(removed)
    assert len(apps) == 3  # immutable edit of the previous config value


@pytest.mark.parametrize("candidate,name", [
    (ROBLOX, " "),
    (ROBLOX, "idle"),
    (ROBLOX, "unknown"),
    (ROBLOX, "x" * 81),
    (ROBLOX, "Bad\\nName"),
    (ROBLOX, "unsafe {field}"),
    ({"process": "javaw.exe", "signature": None}, "Minecraft"),
    ({"process": r"C:\\private\\game.exe", "signature": None}, "Game"),
    ({"process": "chrome.exe", "signature":
      {"kind": "java_class", "value": "org.example.Main"}}, "Browser"),
])
def test_reject_bad_names_and_ambiguous_or_unsafe_identity(candidate, name):
    with pytest.raises(ValueError):
        add_app([], candidate, name)


def test_case_insensitive_duplicate_prevented_across_process_signatures():
    once = add_app([], ROBLOX, "Roblox")
    with pytest.raises(ValueError):
        add_app(once, {"process": "robloxplayerbeta.EXE", "signature": None}, "Another")
    once = add_app(once, MINECRAFT, "Minecraft")
    with pytest.raises(ValueError):
        add_app(once, {"process": "JAVAW.EXE", "signature":
                           {"kind": "java_class", "value": "NET.MINECRAFT.CLIENT.MAIN.MAIN"}},
                "Duplicate")
    assert len(once) == 2


def test_storage_rejects_malformed_corrupted_or_duplicate_entries():
    good = add_app([], ROBLOX, "Roblox")
    for bad in ({"not": "a-list"}, good + good,
                good + [{"process": "x.exe", "signature": None, "name": ""}],
                good + [{"process": "x.exe", "signature": None, "name": "Game", "secret": "s"}]):
        with pytest.raises(ValueError):
            load_apps(bad)


def test_rename_and_remove_cannot_act_on_nonexistent_identity():
    for action in (lambda: rename_app([], "unknown", "Game"),
                   lambda: remove_app([], "unknown")):
        with pytest.raises(ValueError):
            action()
