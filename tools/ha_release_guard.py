"""Validate HA-only versioned previews without deploying any components."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

REQUIRED_WORKFLOWS = frozenset({
    "HA integration CI", "Windows agent CI", "Direct MQTT runtime CI",
    "Recorder coverage CI", "HACS validation", "Security CI",
    "CodeQL", "Python code quality",
})
SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
ROOT = Path(__file__).resolve().parents[1]


def version_and_notes(root: Path) -> tuple[str, str]:
    release = json.loads((root / "release.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "custom_components/hal_gaming_control/manifest.json").read_text(encoding="utf-8"))
    version = release.get("home_assistant")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ValueError("Invalid HA release version")
    if manifest.get("version") != version or manifest.get("domain") != "hal_gaming_control":
        raise ValueError("HA manifest/release.json mismatch")
    notes = (root / "docs/ha_releases.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^## " + re.escape(version) + r"\b[^\n]*\n", notes)
    if not match:
        raise ValueError("Missing versioned HA release notes")
    following = re.search(r"(?m)^## ", notes[match.end():])
    body = notes[match.end(): match.end() + following.start() if following else len(notes)].strip()
    if not body:
        raise ValueError("Empty HA release notes")
    return version, body


def ci_gate(runs: list[dict], sha: str) -> None:
    if not SHA.fullmatch(sha):
        raise ValueError("Invalid source SHA")
    matched = {}
    for run in runs:
        if (run.get("head_sha") != sha or run.get("head_branch") != "main"
                or run.get("event") != "push"):
            continue
        name = run.get("name")
        if name not in REQUIRED_WORKFLOWS:
            continue
        if name not in matched or run.get("run_number", 0) > matched[name].get("run_number", 0):
            matched[name] = run
    missing = sorted(REQUIRED_WORKFLOWS - matched.keys())
    pending = sorted(name for name, run in matched.items() if run.get("status") != "completed")
    failed = sorted(name for name, run in matched.items()
                    if run.get("status") == "completed" and run.get("conclusion") != "success")
    if missing or pending or failed:
        raise ValueError(f"CI gate blocked: missing={missing}; pending={pending}; failed={failed}")


def build_notes(version: str, body: str, sha: str) -> str:
    if not SHA.fullmatch(sha):
        raise ValueError("Invalid SHA")
    return (f"# HAL Gaming Control HA {version} (preview)\n\n"
            f"**HA integration source-only development preview (GitHub regular release for Marketplace version discovery)** pinned to commit " + chr(96) + sha + chr(96) + ". "
            "This GitHub release is not a production certification or a Windows release and contains no Windows executable or signed updater. "
            "Publishing it does not install, update, reload or enable anything in Home Assistant or on a gaming PC.\n\n"
            "**Compatibility:** Windows 0.3.0+ uses MQTT v3-only telemetry; HA's unified telemetry "
            "option must be enabled for the relevant PC before an integrated rollout. "
            "Windows 0.4.0 additionally changes the MQTT device ID to the actual computer name "
            "and requires a supervised per-device migration/re-enrollment.\n\n"
            "**Deployment HOLD:** The live TrueNAS/Windows rollout remains blocked by "
            "[issue #56](https://github.com/mhalak/hal-gaming-control/issues/56), "
            "including backups, trusted Windows signing, Smart App Control and a one-PC pilot. "
            "Local-agent updates remain the development deployment path; HACS publishing is separate.\n\n"
            "**First release after commit-based Marketplace installation:** Some existing installs "
            "may not automatically offer the transition from a commit SHA. When authorized "
            "to update a test HA, refresh the custom repository metadata and, if needed, use "
            "Redownload → select the version, then restart HA as appropriate. A custom repository may refresh from GitHub on a delayed schedule. "
            "Never force an update on the live installation during HOLD.\n\n"
            "## Changes\n\n" + body + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("version", "check", "gate", "notes"))
    parser.add_argument("--sha")
    parser.add_argument("--runs-file")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        version, body = version_and_notes(ROOT)
        if args.command == "version":
            print(version)
            return 0
        if not args.sha or not SHA.fullmatch(args.sha):
            raise ValueError("Exact 40-digit SHA required")
        if args.command == "check":
            current_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            if current_sha != args.sha:
                raise ValueError("Checked-out SHA differs from target")
        elif args.command == "gate":
            if not args.runs_file:
                raise ValueError("--runs-file required")
            data = json.loads(Path(args.runs_file).read_text(encoding="utf-8"))
            ci_gate(data["workflow_runs"], args.sha)
        elif args.command == "notes":
            if not args.output:
                raise ValueError("--output required")
            Path(args.output).write_text(build_notes(version, body, args.sha), encoding="utf-8")
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as err:
        print(str(err), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
