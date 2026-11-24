"""Build a *publicly untrusted* Windows preview download page from reviewed files.

No GitHub Releases, tags, signing requests, installations or network operations.
The caller must separately authorize any PUBLIC deployment of generated output.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
OWNED = (
    "SmartHouseGamingControl/SmartHouseGamingControl.exe",
    "SmartHouseGamingUpdater/SmartHouseGamingUpdater.exe",
)
SCRIPTS = ("install.ps1", "install_helpers.ps1", "uninstall.ps1",
           "config.example.yaml")


def checked_identity(root: Path, sha: str) -> str:
    if not SHA.fullmatch(sha):
        raise ValueError("Exact, lower-case 40-character source SHA required")
    release = json.loads((root / "release.json").read_text(encoding="utf-8"))
    version = release["windows_agent"]
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ValueError("Invalid Windows semantic version")
    if release.get("home_assistant") is None:
        raise ValueError("Missing independent HA version")
    return version


def input_files(root: Path, version: str, sha: str):
    src = root / "windows_agent"
    service = src / "dist" / "SmartHouseGamingControl"
    updater = src / "dist" / "SmartHouseGamingUpdater"
    if not service.is_dir() or not updater.is_dir():
        raise ValueError("Both complete Windows onedir builds are required")
    for rel in OWNED:
        if not (src / "dist" / rel).is_file():
            raise ValueError(f"Missing project-owned EXE: {rel}")
    if (service / "version.txt").read_text(encoding="utf-8").strip() != version:
        raise ValueError("Service version.txt mismatch")
    identity = json.loads((service / "build-info.json").read_text(encoding="utf-8"))
    if (identity.get("component"), identity.get("version"),
            identity.get("commit")) != ("windows_agent", version, sha):
        raise ValueError("Windows build-info provenance mismatch")
    files = []
    for folder in (service, updater):
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise ValueError("Symbolic links are forbidden in Windows package")
            if path.is_file():
                rel = path.relative_to(src / "dist").as_posix()
                files.append((path, rel))
    for name in SCRIPTS:
        p = src / name
        if not p.is_file() or p.is_symlink():
            raise ValueError(f"Missing or linked installer input: {name}")
        files.append((p, name))
    seen = set()
    for _, name in files:
        pp = PurePosixPath(name)
        if name in seen or pp.is_absolute() or ".." in pp.parts:
            raise ValueError("Duplicate or unsafe archive path")
        seen.add(name)
    return files


def render_html(version: str, sha: str, archive: str, digest: str, *, root: bool):
    prefix = f"windows/{version}/" if root else ""
    heading = "Windows companion downloads" if root else f"Windows {version} (UNSIGNED)"
    link = f"{prefix}{archive}"
    other = '<p><a href="../../index.html">All downloads</a></p>' if not root else ""
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>HAL Gaming Control — {html.escape(heading)}</title>"
        '<style>body{font:1rem/1.55 system-ui,sans-serif;max-width:44rem;'
        'padding:2rem;margin:auto}code{overflow-wrap:anywhere}'
        'a{color:#2674bd}strong{font-weight:700}</style></head><body>'
        f"<h1>{html.escape(heading)}</h1>"
        '<p><strong>UNSIGNED DEVELOPMENT PREVIEW — NOT A TRUSTED INSTALLER.</strong></p>'
        '<p>This is an archival public source-built Windows candidate to document '
        'the application form requested by SignPath Foundation. No Authenticode '
        'signature, publisher trust, or Smart App Control acceptance is claimed. '
        'Do not disable Smart App Control, Defender or SmartScreen to use it.</p>'
        f'<p><a href="{html.escape(link, quote=True)}">UNSIGNED Windows {html.escape(version)} ZIP</a></p>'
        f"<p><strong>Source SHA:</strong> <code>{sha}</code><br>"
        f"<strong>ZIP SHA-256:</strong> <code>{digest}</code></p>"
        f'<p><a href="{html.escape(prefix, quote=True)}SHA256SUMS.txt">SHA256SUMS.txt</a> · '
        f'<a href="{html.escape(prefix, quote=True)}manifest.json">Manifest</a></p>'
        '<p>Source, signing policy, privacy policy and installation documentation: '
        '<a href="https://github.com/mhalak/hal-gaming-control">'
        'mhalak/hal-gaming-control</a>.</p>'
        "<p>The Home Assistant integration uses its own GitHub releases and is "
        "not distributed from this Windows page.</p>"
        f"{other}</body></html>\n"
    )


def build(root: Path, output: Path, sha: str):
    version = checked_identity(root, sha)
    if output.exists():
        raise ValueError("Output directory must not already exist")
    files = input_files(root, version, sha)
    page_dir = output / "windows" / version
    page_dir.mkdir(parents=True)
    archive = f"HAL-Gaming-Control-Windows-UNSIGNED-{version}.zip"
    archive_path = page_dir / archive
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as zipped:
        for path, name in files:
            zipped.write(path, arcname=name)
    with zipfile.ZipFile(archive_path) as zipped:
        bad = zipped.testzip()
        if bad:
            raise ValueError(f"Corrupted archive member: {bad}")
        if not set(OWNED).issubset(zipped.namelist()):
            raise ValueError("Missing owned EXE in package")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (page_dir / "SHA256SUMS.txt").write_text(f"{digest}  {archive}\n", encoding="utf-8")
    manifest = {
        "project": "HAL Gaming Control",
        "component": "windows_agent",
        "version": version,
        "source_sha": sha,
        "archive": archive,
        "sha256": digest,
        "signature_status": "NotSigned",
        "trusted_for_installation": False,
        "ha_release_unchanged": True,
    }
    (page_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (page_dir / "index.html").write_text(
        render_html(version, sha, archive, digest, root=False), encoding="utf-8")
    output.joinpath("index.html").write_text(
        render_html(version, sha, archive, digest, root=True), encoding="utf-8")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sha", required=True)
    args = p.parse_args()
    try:
        result = build(args.root.resolve(), args.output.resolve(), args.sha)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
