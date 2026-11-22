import pytest

from gaming_control.identity import resolve_identity


def test_windows_name_is_the_only_identity_and_no_file_is_written(tmp_path):
    config = {"mqtt": {"host": "broker"}}
    old = tmp_path / "device_id"
    old.write_text("desktop_lucija\n", encoding="ascii")

    result = resolve_identity(config, tmp_path / "config.yaml", computer_name="DESKTOP-F29J1R1")

    assert result["device"] == {"id": "DESKTOP-F29J1R1", "name": "DESKTOP-F29J1R1"}
    assert config == {"mqtt": {"host": "broker"}}
    assert old.read_text(encoding="ascii") == "desktop_lucija\n"


def test_renaming_windows_host_also_changes_mqtt_identity(tmp_path):
    config = {"mqtt": {"host": "broker"}}
    first = resolve_identity(config, tmp_path / "config.yaml", computer_name="DESKTOP-OLD")
    next_ = resolve_identity(config, tmp_path / "config.yaml", computer_name="DESKTOP-NEW")
    assert first["device"]["id"] == "DESKTOP-OLD"
    assert next_["device"]["id"] == "DESKTOP-NEW"
    assert not (tmp_path / "device_id").exists()


@pytest.mark.parametrize("device", [
    {"id": "desktop_lucija"},
    {"name": "Lucija"},
    {"id": "desktop_lucija", "name": "Lucija"},
    {},
    "desktop_lucija",
])
def test_user_configured_device_identity_is_rejected(tmp_path, device):
    with pytest.raises(ValueError, match="device"):
        resolve_identity({"mqtt": {"host": "broker"}, "device": device},
                         tmp_path / "config.yaml", computer_name="DESKTOP-LUCIJA")


@pytest.mark.parametrize("hostname", ["", " ", "PC\nHACK", "A" * 65, "bad/name", "a.b", "föö"])
def test_invalid_os_hostnames_fail_closed(tmp_path, hostname):
    with pytest.raises(ValueError, match="Windows computer name"):
        resolve_identity({}, tmp_path / "config.yaml", computer_name=hostname)
    assert not (tmp_path / "device_id").exists()


def test_invalid_agent_config_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="configuration"):
        resolve_identity(None, tmp_path / "config.yaml", computer_name="DESKTOP-LUCIJA")
