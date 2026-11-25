"""Static guard: SignPath application prep cannot accidentally publish binaries."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_policy_and_privacy_are_public_and_linked_from_homepage_and_download():
    home = read("README.md")
    download = read("docs/windows_distribution.md")
    policy = read("CODE_SIGNING_POLICY.md")
    privacy = read("PRIVACY.md")
    assert "[Code signing policy](CODE_SIGNING_POLICY.md)" in home
    assert "[Privacy policy](PRIVACY.md)" in home
    assert "Free code signing provided by SignPath.io, certificate by SignPath Foundation." in policy
    assert "Free code signing provided by SignPath.io, certificate by SignPath Foundation." in download
    for text in (home, policy, privacy, download):
        assert "HAL Gaming Control" in text
    for required in ("Authors", "Reviewers", "approver", "privacy", "LocalSystem",
                     "manual", "SignPath", "not", "0.4.3"):
        assert required.casefold() in (policy + download).casefold()
    assert "NO" in download.upper() and "SIGNED" in download.upper()
    assert "previous" in download.lower() or "prior" in download.lower()


def test_operator_only_unsigned_candidate_workflow_is_fail_closed():
    cfg = read(".github/workflows/windows-signing-candidate.yml")
    assert "workflow_dispatch:" in cfg
    assert "pull_request:" not in cfg
    assert "issue_comment:" in cfg
    assert "types: [created]" in cfg
    assert "github.event.issue.number == 9" in cfg
    assert "github.event.issue.pull_request == null" in cfg
    assert "github.event.comment.user.login == 'mhalak'" in cfg
    assert "startsWith(github.event.comment.body, '/build-windows-candidate ')" in cfg
    assert '$env:RELEASE_COMMAND -cne "/build-windows-candidate $version"' in cfg
    assert "contents: read" in cfg
    assert "contents: write" not in cfg
    assert "github.ref == 'refs/heads/main'" in cfg
    assert "github.actor == 'mhalak'" in cfg
    assert "runs-on: windows-latest" in cfg
    assert "persist-credentials: false" in cfg
    assert "retention-days: 1" in cfg
    assert "Get-AuthenticodeSignature" in cfg
    assert "NotSigned" in cfg
    assert "pyinstaller" not in cfg.lower()  # compile through reviewed build.ps1
    for forbidden in ("gh release create", "SIGNPATH_API_TOKEN",
                      "github-action-submit-signing-request", "windows-release-signing-key",
                      "upload-release-asset", "Start-Service", "install.ps1 -Config"):
        assert forbidden not in cfg
    for used in ("actions/checkout@3d3c42e5", "actions/setup-python@6d4fd22",
                 "actions/upload-artifact@ea165f8d"):
        assert used in cfg


def test_build_embeds_owned_version_metadata_before_pyinstaller():
    ps = read("windows_agent/build.ps1")
    assert "--filename SmartHouseGamingControl.exe" in ps
    assert "--filename SmartHouseGamingUpdater.exe" in ps
    assert ps.count("--version-file") == 2
    assert "release_identity.py" in ps
    assert "version_metadata.py" in ps
    # Independently declared component versions; the Windows build does not bump HA.
    release = json.loads(read("release.json"))
    manifest = json.loads(read("custom_components/hal_gaming_control/manifest.json"))
    assert release["home_assistant"] == manifest["version"]
    for component in ("home_assistant", "windows_agent"):
        assert re.fullmatch(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})", release[component])
    assert "sync-ha" not in ps


def test_windows_distribution_is_not_mistaken_for_hacs_release():
    download = read("docs/windows_distribution.md")
    assert "GitHub Releases" in download
    assert "HA" in download
    assert "no approved" in download.lower()
    assert "publicly trusted" in download.lower()
    assert "separate" in download.lower()
