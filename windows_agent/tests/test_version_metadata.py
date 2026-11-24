"""SignPath PE metadata is version-consistent and restricted to HAL binaries."""
import ast
from pathlib import Path
import subprocess
import sys

import pytest

from version_metadata import OWNED, PROJECT, version_resource


@pytest.mark.parametrize("filename", sorted(OWNED))
def test_owned_executable_has_matching_pe_product_and_version(filename):
    value = version_resource("0.4.3", filename)
    assert ast.parse(value)
    assert "StringStruct('ProductName', 'HAL Gaming Control')" in value
    assert "StringStruct('ProductVersion', '0.4.3')" in value
    assert "StringStruct('FileVersion', '0.4.3')" in value
    assert "(0, 4, 3, 0)" in value
    assert f"StringStruct('OriginalFilename', '{filename}')" in value
    assert "SignPath Foundation" not in value  # signature is provided externally
    assert PROJECT == "HAL Gaming Control"


@pytest.mark.parametrize("invalid", ["0.4", "v0.4.3", "0.04.3", "1.2.3.4",
                                    "0.4.3-dev", "../secret", "", None, True, 3])
def test_invalid_versions_cannot_be_embedded(invalid):
    with pytest.raises(ValueError):
        version_resource(invalid, "SmartHouseGamingControl.exe")


@pytest.mark.parametrize("unowned", ["cmd.exe", "python312.dll",
                                     "libcrypto.dll", "OtherApp.exe", ""])
def test_upstream_or_unowned_files_cannot_be_branded(unowned):
    with pytest.raises(ValueError):
        version_resource("0.4.3", unowned)


def test_version_metadata_cli_generates_only_requested_file(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "resources" / "agent.txt"
    subprocess.run(
        [sys.executable, str(root / "version_metadata.py"),
         "--version", "0.4.3", "--filename", "SmartHouseGamingControl.exe",
         "--output", str(output)],
        check=True, timeout=15)
    assert ast.parse(output.read_text(encoding="utf-8"))
    assert list(tmp_path.rglob("*.txt")) == [output]
    assert not list(tmp_path.rglob("*.exe"))
