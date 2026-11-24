"""Stage provenance-checked wheel/CPython license texts for a Windows preview.

Only copies authoritative files installed into the builder's *actual* Python
environment; this is not a legal review or a Windows signing request.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict:
    data = json.loads(
        (root / "windows_agent" / "preview-license-snapshot.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(data.get("distributions"), dict) or not data.get("python"):
        raise ValueError("Invalid audited preview license snapshot")
    return data


def _license_entries(distribution) -> list[tuple[Path, PurePosixPath]]:
    """Copy wheel-native license text; never synthesize a guessed license."""
    found = []
    for item in distribution.files or ():
        name = PurePosixPath(str(item).replace("\\", "/"))
        lower_parts = tuple(part.casefold() for part in name.parts)
        filename = name.name.casefold()
        if ("licenses" not in lower_parts and
                not filename.startswith(("license", "copying", "notice"))):
            continue
        if name.is_absolute() or ".." in name.parts:
            raise ValueError("Unsafe installed wheel license path")
        location = Path(distribution.locate_file(item))
        if not location.is_file() or location.is_symlink():
            raise ValueError(f"Missing/linked installed wheel license: {name}")
        if location.stat().st_size == 0 or location.stat().st_size > 1024 * 1024:
            raise ValueError(f"Empty or oversized installed wheel license: {name}")
        found.append((location, name))
    if not found:
        raise ValueError(f"No installed wheel license texts: {distribution.metadata['Name']}")
    return found


def stage(root: Path, *, python_home: Path | None = None,
          python_version: str | None = None,
          find_distribution=metadata.distribution) -> dict:
    root = root.resolve()
    expected = _snapshot(root)
    if (python_version or platform.python_version()) != expected["python"]:
        raise ValueError("Actual CPython version does not match audited Windows preview")
    base = root / "windows_agent" / "dist" / "licenses"
    if base.exists():
        raise ValueError("License stage must not already exist")
    source_python = (python_home or Path(sys.base_prefix)) / "LICENSE.txt"
    if not source_python.is_file() or source_python.is_symlink():
        raise ValueError("CPython LICENSE.txt missing from selected build interpreter")
    sources: list[tuple[Path, Path]] = [(source_python, Path("Python") / "LICENSE.txt")]
    found_versions = {}
    for name, exact_version in expected["distributions"].items():
        dist = find_distribution(name)
        if dist.version != exact_version:
            raise ValueError(f"{name} version drift: {dist.version} != {exact_version}")
        found_versions[name] = dist.version
        for location, rel in _license_entries(dist):
            sources.append((location, Path(name) / Path(*rel.parts)))
    seen = set()
    checksums = {}
    for source, relative in sources:
        logical = relative.as_posix()
        if logical in seen or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Duplicate/unsafe staged license path")
        seen.add(logical)
        checksums[f"licenses/{logical}"] = _digest(source)
    base.mkdir(parents=True)
    for source, relative in sources:
        destination = base / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if _digest(destination) != checksums[f"licenses/{relative.as_posix()}"]:
            raise ValueError("Staged license content changed")
    manifest = {
        "schema": 1,
        "python": expected["python"],
        "distributions": found_versions,
        "files": checksums,
        "legal_review_complete": False,
    }
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = stage(args.root)
        print(json.dumps({"licenses_staged": len(result["files"]),
                          "legal_review_complete": False}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, metadata.PackageNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
