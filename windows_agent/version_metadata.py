"""Generate deterministic PyInstaller PE version resources for HAL-owned EXEs.

Windows code signing requires matching product/version metadata for all
first-party executables; this file is run before PyInstaller on Windows.
It does NOT sign code or assign SignPath publisher identity.
"""
import argparse
from pathlib import Path
import re

PROJECT = "HAL Gaming Control"
OWNED = {
    "SmartHouseGamingControl.exe": "HAL Gaming Control Windows service",
    "SmartHouseGamingUpdater.exe": "HAL Gaming Control Windows updater",
}
VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")


def version_resource(version, filename):
    if type(version) is not str or VERSION.fullmatch(version) is None:
        raise ValueError("Windows version must be major.minor.patch")
    if filename not in OWNED:
        raise ValueError("Refusing to assign HAL metadata to an unowned binary")
    quad = tuple(int(part) for part in version.split(".")) + (0,)
    if any(part > 65535 for part in quad):
        raise ValueError("Windows file version component exceeds PE limit")
    description = OWNED[filename]
    return (
        "# Auto-generated: owned Windows EXE version metadata (NOT signature)\n"
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(filevers={!r}, prodvers={!r}, mask=0x3f, flags=0x0,\n"
        "                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        "    StringStruct('CompanyName', 'HAL Systems'),\n"
        "    StringStruct('FileDescription', {!r}),\n"
        "    StringStruct('FileVersion', {!r}),\n"
        "    StringStruct('InternalName', {!r}),\n"
        "    StringStruct('LegalCopyright', 'Copyright (c) 2026 HAL Gaming Control contributors'),\n"
        "    StringStruct('OriginalFilename', {!r}),\n"
        "    StringStruct('ProductName', {!r}),\n"
        "    StringStruct('ProductVersion', {!r})\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]\n"
        ")\n"
    ).format(quad, quad, description, version, filename[:-4],
             filename, PROJECT, version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--filename", choices=sorted(OWNED), required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    content = version_resource(args.version, args.filename)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
