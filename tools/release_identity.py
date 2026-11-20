"""Validate independent component versions and identify a clean source build."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ("windows_agent", "home_assistant")
VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")
SHA = re.compile(r"[0-9a-f]{40}")
HA_MANIFEST = Path("custom_components/smarthouse_gaming/manifest.json")


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


def read_release(root):
    release = _read_json(root / "release.json")
    if not isinstance(release, dict) or set(release) != {"release", *COMPONENTS}:
        raise ValueError("Invalid release schema")
    label = release["release"]
    if not isinstance(label, str) or not label.strip() or any(ord(c) < 32 for c in label):
        raise ValueError("Invalid release label")
    if not all(_valid_version(release[key]) for key in COMPONENTS):
        raise ValueError("Invalid component version")
    manifest = _read_json(root / HA_MANIFEST)
    if not isinstance(manifest, dict) or manifest.get("version") != release["home_assistant"]:
        raise ValueError("HA manifest version differs from release.json")
    return release


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "identity"))
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--version")
    args = parser.parse_args()
    try:
        if args.command == "check":
            if args.component is not None or args.version is not None:
                raise ValueError("check accepts no component or version")
            read_release(ROOT)
            print("Release metadata consistent")
        else:
            print(json.dumps(build_identity(ROOT, args.component, args.version)))
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
