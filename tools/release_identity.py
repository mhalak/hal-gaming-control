"""Validate independent component versions and identify a clean source build."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ("windows_agent", "home_assistant")
VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")
SHA = re.compile(r"[0-9a-f]{40}")
HA_MANIFEST = Path("custom_components/parental_control/manifest.json")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, ValueError) as error:
        raise ValueError(f"Invalid release input: {path.name}") from error


def _valid_version(value):
    return isinstance(value, str) and VERSION.fullmatch(value) is not None


def _release_metadata(root):
    release = _read_json(root / "release.json")
    if not isinstance(release, dict) or set(release) != {"release", *COMPONENTS}:
        raise ValueError("Invalid release schema")
    label = release["release"]
    if not isinstance(label, str) or not label.strip() or any(ord(c) < 32 for c in label):
        raise ValueError("Invalid release label")
    if not all(_valid_version(release[key]) for key in COMPONENTS):
        raise ValueError("Invalid component version")
    return release


def read_release(root):
    release = _release_metadata(root)
    manifest = _read_json(root / HA_MANIFEST)
    if not isinstance(manifest, dict) or manifest.get("version") != release["home_assistant"]:
        raise ValueError("HA manifest version differs from release.json")
    return release


def sync_ha_manifest(root):
    """Explicit developer operation; never called automatically by a build."""
    release = _release_metadata(root)
    path = root / HA_MANIFEST
    manifest = _read_json(path)
    if not isinstance(manifest, dict) or manifest.get("domain") != "parental_control":
        raise ValueError("Unexpected HA manifest")
    if manifest.get("version") != release["home_assistant"]:
        manifest["version"] = release["home_assistant"]
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def _git(root, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True,
            text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Git checkout required for build identity") from error


def build_identity(root, component, requested_version=None):
    if component not in COMPONENTS:
        raise ValueError("Unknown component")
    release = read_release(root)
    version = release[component]
    if requested_version is not None and requested_version != version:
        raise ValueError("Requested version differs from release.json")
    commit = _git(root, "rev-parse", "HEAD")
    if not SHA.fullmatch(commit):
        raise ValueError("Invalid Git commit")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Build requires a clean Git checkout")
    return {"release": release["release"], "component": component,
            "version": version, "commit": commit}



def stage_ha(root, output):
    """Stage tracked HA files, with reviewed source identity, outside the checkout."""
    root = Path(root).resolve()
    destination = Path(output).expanduser().resolve()
    if destination == root or root in destination.parents:
        raise ValueError("HA staging must stay outside the source checkout")
    identity = build_identity(root, "home_assistant")
    if destination.exists():
        raise ValueError("Staging destination already exists")
    prefix = HA_MANIFEST.parent.as_posix() + "/"
    files = _git(root, "ls-files", "-z", "--", prefix).split("\0")
    files = [name for name in files if name]
    if HA_MANIFEST.as_posix() not in files:
        raise ValueError("Missing tracked HA manifest")
    # Create a new destination, never merge over a previous installation.
    destination.mkdir(parents=True)
    try:
        for name in files:
            if not name.startswith(prefix):
                raise ValueError("Invalid component path")
            relative = Path(name[len(prefix):])
            if not relative.parts or ".." in relative.parts or relative.is_absolute():
                raise ValueError("Invalid tracked source path")
            source = root / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("Untrusted HA source file")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        if build_identity(root, "home_assistant") != identity:
            raise ValueError("Source changed during staging")
        (destination / "build-info.json").write_text(
            json.dumps(identity, sort_keys=True) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "identity", "sync-ha", "stage-ha"))
    parser.add_argument("--output")
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--version")
    args = parser.parse_args()
    try:
        if args.command in ("check", "sync-ha"):
            if args.component is not None or args.version is not None or args.output is not None:
                raise ValueError("check/sync-ha accepts no component, version or output")
            if args.command == "sync-ha":
                sync_ha_manifest(ROOT)
            read_release(ROOT)
            print("Release metadata consistent")
        elif args.command == "stage-ha":
            if args.component is not None or args.version is not None or not args.output:
                raise ValueError("stage-ha requires only --output")
            print(json.dumps(stage_ha(ROOT, args.output)))
        else:
            if args.output is not None or args.component is None:
                raise ValueError("identity requires --component and no --output")
            print(json.dumps(build_identity(ROOT, args.component, args.version)))
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
