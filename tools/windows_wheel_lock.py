"""Verify an exact Windows wheelhouse and emit hash-required offline requirements.

Only used for the reviewed owner-controlled Windows 3.12.10 / win_amd64
preview build. No network access, publication, signing or installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import re
import sys

LOCK_NAME = "preview-wheels.sha256.json"
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
NORMALIZE = re.compile(r"[-_.]+")


def _canonical(name: str) -> str:
    return NORMALIZE.sub("-", name).lower()


def _constraints(path: Path) -> dict[str, str]:
    packages = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        requirement = line.split(";", 1)[0].strip()
        match = re.fullmatch(r"([A-Za-z0-9._-]+)==([A-Za-z0-9.+]+)", requirement)
        if not match:
            raise ValueError("Unpinned or invalid Windows preview constraint")
        name = _canonical(match.group(1))
        if name in packages:
            raise ValueError(f"Duplicate Windows preview constraint: {name}")
        packages[name] = match.group(2)
    if len(packages) != 19:
        raise ValueError("Windows Preview wheel lock requires exactly 19 constraints")
    return packages


def _wheel_identity(filename: str) -> tuple[str, str]:
    if not filename.endswith(".whl") or "/" in filename or "\\" in filename:
        raise ValueError("Invalid or unsafe wheel filename")
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) != 5:
        raise ValueError(f"Unrecognized wheel filename: {filename}")
    name, version, _python_tag, _abi_tag, platform_tag = parts
    if not re.fullmatch(r"[A-Za-z0-9_.]+", name):
        raise ValueError(f"Invalid wheel distribution name: {filename}")
    if not re.fullmatch(r"[A-Za-z0-9.!+]+", version):
        raise ValueError(f"Invalid wheel version: {filename}")
    if platform_tag not in {"any", "win_amd64"}:
        raise ValueError(f"Non-Windows/wrong-architecture wheel: {filename}")
    return _canonical(name), version


def _read_lock(root: Path) -> tuple[dict, dict]:
    manifest = json.loads((root / "windows_agent" / LOCK_NAME).read_text(
        encoding="utf-8"
    ))
    if (manifest.get("schema") != 1 or manifest.get("platform") != "win_amd64"
            or manifest.get("python") != "3.12.10"
            or not isinstance(manifest.get("wheels"), list)
            or len(manifest["wheels"]) != 19):
        raise ValueError("Invalid or incomplete Windows wheel lock")
    constraints = _constraints(root / "windows_agent/preview-constraints.txt")
    entries = {}
    for item in manifest["wheels"]:
        if not isinstance(item, dict) or set(item) != {"filename", "sha256"}:
            raise ValueError("Invalid wheel lock entry")
        name, version = _wheel_identity(item["filename"])
        if (name not in constraints or version != constraints[name]
                or not SHA256.fullmatch(item["sha256"])):
            raise ValueError(f"Wheel lock conflicts with exact constraints: {name}")
        if name in entries:
            raise ValueError(f"Duplicate locked wheel: {name}")
        entries[name] = item
    if set(entries) != set(constraints):
        raise ValueError("Wheel lock is missing constrained dependencies")
    return manifest, entries


def verify(root: Path, wheelhouse: Path, output: Path, *,
           require_windows: bool = False) -> dict:
    root, wheelhouse = root.resolve(), wheelhouse.resolve()
    manifest, entries = _read_lock(root)
    if require_windows and (sys.platform != "win32"
                            or platform.python_version() != manifest["python"]
                            or platform.machine().lower() not in {"amd64", "x86_64"}):
        raise ValueError("Locked wheelhouse requires CPython 3.12.10 Windows AMD64")
    if not wheelhouse.is_dir() or output.exists():
        raise ValueError("Wheelhouse missing or output already exists")
    actual = list(wheelhouse.iterdir())
    if (len(actual) != len(entries)
            or any(p.is_symlink() or not p.is_file() or p.suffix != ".whl"
                   for p in actual)):
        raise ValueError("Unexpected, linked or missing file in wheelhouse")
    expected_files = {item["filename"] for item in entries.values()}
    if {p.name for p in actual} != expected_files:
        raise ValueError("Wheelhouse filenames differ from reviewed lock")
    for item in entries.values():
        source = wheelhouse / item["filename"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"Wheel SHA-256 mismatch: {item['filename']}")
    lines = [
        "# Generated from reviewed Windows Preview wheel lock; do not edit.",
        "# Only install from exact verified local wheelhouse with --require-hashes.",
    ]
    for name, item in sorted(entries.items()):
        _distribution, version = _wheel_identity(item["filename"])
        lines.append(f"{name}=={version} --hash=sha256:{item['sha256']}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"validated_wheels": len(entries), "python": manifest["python"],
            "platform": manifest["platform"], "requirements": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.root, args.wheelhouse, args.output,
                                require_windows=True), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
