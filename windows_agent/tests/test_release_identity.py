"""Test release identity without building binaries or publishing artifacts."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHA = "1234567890abcdef" * 2 + "12345678"
RELEASE = {"release": "HAL Gaming Control Preview 21", "windows_agent": "0.4.0",
           "home_assistant": "0.12.0"}


def release_tool():
    spec = importlib.util.spec_from_file_location("release_identity", ROOT / "tools/release_identity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "release.json").write_text(json.dumps(RELEASE), encoding="utf-8")
    component = tmp_path / "custom_components" / "hal_gaming_control"
    component.mkdir(parents=True)
    (component / "manifest.json").write_text(
        json.dumps({"domain": "hal_gaming_control", "version": "0.12.0"}), encoding="utf-8")
    return tmp_path


def test_repository_release_metadata_is_consistent():
    release = release_tool().read_release(ROOT)
    assert release == RELEASE
    assert release["home_assistant"] == json.loads(
        (ROOT / "custom_components/hal_gaming_control/manifest.json").read_text(encoding="utf-8")
    )["version"]


def test_release_manifest_chooses_independent_component_versions(checkout):
    assert release_tool().read_release(checkout) == RELEASE


@pytest.mark.parametrize("value", ["0.02.2", "v0.2.2", "0.2.2-beta", "0.2", True, None, 2])
def test_release_rejects_invalid_numeric_component_version(checkout, value):
    (checkout / "release.json").write_text(
        json.dumps(RELEASE | {"windows_agent": value}), encoding="utf-8")
    with pytest.raises(ValueError):
        release_tool().read_release(checkout)


def test_release_rejects_ha_version_drift(checkout):
    (checkout / "custom_components/hal_gaming_control/manifest.json").write_text(
        '{"version":"0.4.2"}', encoding="utf-8")
    with pytest.raises(ValueError):
        release_tool().read_release(checkout)


@pytest.mark.parametrize("raw", [
    "[]", "{}", "null", "{broken", json.dumps(RELEASE | {"extra": "bad"}),
    json.dumps(RELEASE | {"release": ""}),
    '{"release":"x","windows_agent":"0.2.2","windows_agent":"0.2.4","home_assistant":"0.4.3"}',
])
def test_release_rejects_malformed_or_ambiguous_manifest(checkout, raw):
    (checkout / "release.json").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        release_tool().read_release(checkout)


def test_release_missing_file_is_not_a_legacy_default(checkout):
    (checkout / "release.json").unlink()
    with pytest.raises(ValueError):
        release_tool().read_release(checkout)


@pytest.mark.parametrize("component,version", [("windows_agent", "0.4.0"), ("home_assistant", "0.12.0")])
def test_build_identity_is_bound_to_clean_revision(checkout, component, version):
    tool = release_tool()
    with patch.object(tool, "_git", side_effect=lambda root, *args:
                      SHA if args == ("rev-parse", "HEAD") else ""):
        identity = tool.build_identity(checkout, component)
    assert identity == {"release": RELEASE["release"], "component": component,
                        "version": version, "commit": SHA}


@pytest.mark.parametrize("override", ["0.2.1", "0.2.2", "0.2.3", "0.2.4", "garbage"])
def test_build_rejects_explicit_version_mismatch(checkout, override):
    tool = release_tool()
    with patch.object(tool, "_git", side_effect=lambda root, *args:
                      SHA if args == ("rev-parse", "HEAD") else ""):
        with pytest.raises(ValueError):
            tool.build_identity(checkout, "windows_agent", requested_version=override)


def test_build_allows_matching_explicit_version(checkout):
    tool = release_tool()
    with patch.object(tool, "_git", side_effect=lambda root, *args:
                      SHA if args == ("rev-parse", "HEAD") else ""):
        assert tool.build_identity(checkout, "windows_agent", requested_version="0.4.0")["version"] == "0.4.0"


@pytest.mark.parametrize("status", [" M release.json", "?? untracked.py"])
def test_build_rejects_dirty_source(checkout, status):
    tool = release_tool()
    with patch.object(tool, "_git", side_effect=lambda root, *args:
                      SHA if args == ("rev-parse", "HEAD") else status):
        with pytest.raises(ValueError):
            tool.build_identity(checkout, "windows_agent")


@pytest.mark.parametrize("sha", ["unknown", "1234567", "z" * 40, ""])
def test_build_rejects_invalid_commit(checkout, sha):
    tool = release_tool()
    with patch.object(tool, "_git", side_effect=lambda root, *args:
                      sha if args == ("rev-parse", "HEAD") else ""):
        with pytest.raises(ValueError):
            tool.build_identity(checkout, "windows_agent")


def test_build_rejects_unknown_component(checkout):
    with pytest.raises(ValueError):
        release_tool().build_identity(checkout, "other")


def test_sync_ha_only_updates_version_and_is_idempotent(checkout):
    tool = release_tool()
    manifest = checkout / "custom_components/hal_gaming_control/manifest.json"
    content = {"domain": "hal_gaming_control", "version": "0.4.2", "name": "Example"}
    manifest.write_text(json.dumps(content), encoding="utf-8")
    tool.sync_ha_manifest(checkout)
    assert json.loads(manifest.read_text(encoding="utf-8")) == content | {"version": "0.12.0"}
    previous = manifest.read_bytes()
    tool.sync_ha_manifest(checkout)
    assert manifest.read_bytes() == previous
    assert tool.read_release(checkout) == RELEASE


def test_sync_ha_rejects_wrong_domain(checkout):
    manifest = checkout / "custom_components/hal_gaming_control/manifest.json"
    manifest.write_text('{"domain":"other","version":"0.4.2"}', encoding="utf-8")
    previous = manifest.read_bytes()
    with pytest.raises(ValueError):
        release_tool().sync_ha_manifest(checkout)
    assert manifest.read_bytes() == previous


def test_real_git_identity_and_dirty_guard(checkout):
    import subprocess
    def git(*args):
        return subprocess.run(["git", "-C", str(checkout), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init")
    git("add", ".")
    git("-c", "user.name=Release test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-m", "test")
    tool = release_tool()
    assert tool.build_identity(checkout, "windows_agent")["commit"] == git("rev-parse", "HEAD")
    (checkout / "release.json").write_text(json.dumps(RELEASE) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean"):
        tool.build_identity(checkout, "windows_agent")


def test_stage_ha_from_reviewed_git_checkout(checkout):
    import subprocess
    def git(*args):
        return subprocess.run(["git", "-C", str(checkout), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    component = checkout / "custom_components" / "hal_gaming_control"
    (component / "sensor.py").write_text("EXAMPLE = True\n", encoding="utf-8")
    git("init")
    git("add", ".")
    git("-c", "user.name=Release test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-m", "test")
    sha = git("rev-parse", "HEAD")
    destination = checkout.parent / (checkout.name + "-ha-staged")
    tool = release_tool()
    assert tool.stage_ha(checkout, destination) == {
        "release": RELEASE["release"], "component": "home_assistant",
        "version": "0.12.0", "commit": sha}
    assert (destination / "sensor.py").read_text(encoding="utf-8") == "EXAMPLE = True\n"
    assert json.loads((destination / "build-info.json").read_text())["commit"] == sha
    assert not (component / "build-info.json").exists()
    with pytest.raises(ValueError):
        tool.stage_ha(checkout, destination)
    (component / "sensor.py").write_text("CHANGED\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean"):
        tool.stage_ha(checkout, checkout.parent / (checkout.name + "-other-staged"))
