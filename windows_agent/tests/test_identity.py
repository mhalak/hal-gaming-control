import re

import pytest

from gaming_control.identity import resolve_identity


def test_new_install_generates_stable_id_and_uses_live_windows_name(tmp_path):
    config = {"mqtt": {"host": "broker"}}
    one = resolve_identity(config, tmp_path / "config.yaml", computer_name="DESKTOP-LUCIJA")
    assert re.fullmatch(r"pc_[0-9a-f]{32}", one["device"]["id"])
    assert one["device"]["name"] == "DESKTOP-LUCIJA"
    assert config == {"mqtt": {"host": "broker"}}
    assert (tmp_path / "device_id").read_text().strip() == one["device"]["id"]
    two = resolve_identity(config, tmp_path / "config.yaml", computer_name="RENAMED-PC")
    assert two["device"]["id"] == one["device"]["id"]
    assert two["device"]["name"] == "RENAMED-PC"


def test_legacy_id_is_preserved_even_after_removing_device_section(tmp_path):
    path = tmp_path / "config.yaml"
    legacy = {"device": {"id": "lucija_pc", "name": "Hardcoded Gaming PC"}}
    one = resolve_identity(legacy, path, computer_name="DESKTOP-LUCIJA")
    assert one["device"] == {"id": "lucija_pc", "name": "DESKTOP-LUCIJA"}
    assert (tmp_path / "device_id").read_text().strip() == "lucija_pc"
    two = resolve_identity({}, path, computer_name="NEW-HOST")
    assert two["device"] == {"id": "lucija_pc", "name": "NEW-HOST"}


def test_device_ids_are_distinct_between_installations(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert resolve_identity({}, a / "config.yaml", computer_name="SAME-PC")["device"]["id"] != resolve_identity({}, b / "config.yaml", computer_name="SAME-PC")["device"]["id"]


def test_existing_id_mismatch_fails_closed(tmp_path):
    (tmp_path / "device_id").write_text("old_pc\n")
    with pytest.raises(ValueError, match="conflicts"):
        resolve_identity({"device": {"id": "new_pc"}}, tmp_path / "config.yaml", computer_name="PC")
    assert (tmp_path / "device_id").read_text() == "old_pc\n"


@pytest.mark.parametrize("content", ["", "bad id", "a" * 65, "../../another_pc"])
def test_corrupt_persisted_identity_is_not_replaced(tmp_path, content):
    (tmp_path / "device_id").write_text(content)
    with pytest.raises(ValueError, match="device ID"):
        resolve_identity({}, tmp_path / "config.yaml", computer_name="PC")


@pytest.mark.parametrize("name", ["", " ", "PC\nHACK", "A" * 101])
def test_invalid_hostnames_are_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="computer name"):
        resolve_identity({}, tmp_path / "config.yaml", computer_name=name)
    assert not (tmp_path / "device_id").exists()


def test_legacy_invalid_id_rejected_before_persisting(tmp_path):
    with pytest.raises(ValueError, match="device ID"):
        resolve_identity({"device": {"id": "a/b"}}, tmp_path / "config.yaml", computer_name="PC")
    assert not (tmp_path / "device_id").exists()
