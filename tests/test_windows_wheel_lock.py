"""Release safety: exact Windows wheel hashes must gate every public candidate."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "windows_wheel_lock", ROOT / "tools/windows_wheel_lock.py"
)
lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lock)


class WheelLockTests(unittest.TestCase):
    def fixture(self, root: Path):
        source = json.loads(
            (ROOT / "windows_agent/preview-wheels.sha256.json").read_text()
        )
        folder = root / "windows_agent"
        folder.mkdir()
        shutil.copyfile(ROOT / "windows_agent/preview-constraints.txt",
                        folder / "preview-constraints.txt")
        wheels = root / "wheelhouse"
        wheels.mkdir()
        for item in source["wheels"]:
            content = ("synthetic test wheel: " + item["filename"]).encode()
            (wheels / item["filename"]).write_bytes(content)
            item["sha256"] = hashlib.sha256(content).hexdigest()
        (folder / "preview-wheels.sha256.json").write_text(
            json.dumps(source), encoding="utf-8"
        )
        return wheels, source

    def test_committed_lock_has_exactly_19_reviewed_windows_wheels(self):
        manifest, entries = lock._read_lock(ROOT)
        self.assertEqual(len(entries), 19)
        self.assertEqual(manifest["platform"], "win_amd64")
        self.assertEqual(manifest["python"], "3.12.10")
        self.assertEqual(manifest["source_run"], 45475227399)
        self.assertEqual(len({v["filename"] for v in entries.values()}), 19)

    def test_local_hash_verification_and_offline_requirements(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheels, _ = self.fixture(root)
            target = root / "requirements-hashed.txt"
            result = lock.verify(root, wheels, target)
            self.assertEqual(result["validated_wheels"], 19)
            lines = [x for x in target.read_text().splitlines()
                     if not x.startswith("#")]
            self.assertEqual(len(lines), 19)
            self.assertTrue(all(" --hash=sha256:" in line for line in lines))
            self.assertTrue(all("==" in line for line in lines))
            self.assertTrue(all("http" not in line for line in lines))
            with self.assertRaisesRegex(ValueError, "already exists"):
                lock.verify(root, wheels, target)

    def test_tampering_and_extra_wheel_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheels, data = self.fixture(root)
            (wheels / data["wheels"][0]["filename"]).write_bytes(b"modified!")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                lock.verify(root, wheels, root / "tampered.txt")
            (wheels / data["wheels"][0]["filename"]).write_bytes(
                ("synthetic test wheel: " + data["wheels"][0]["filename"]).encode()
            )
            (wheels / "untrusted-1.0-py3-none-any.whl").write_bytes(b"extra")
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                lock.verify(root, wheels, root / "extra.txt")

    def test_wrong_version_and_missing_package_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheels, data = self.fixture(root)
            (wheels / data["wheels"][0]["filename"]).unlink()
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                lock.verify(root, wheels, root / "missing.txt")
            (wheels / data["wheels"][0]["filename"]).write_bytes(
                ("synthetic test wheel: " + data["wheels"][0]["filename"]).encode()
            )
            data["wheels"][0]["filename"] = "altgraph-0.0.0-py3-none-any.whl"
            (root / "windows_agent/preview-wheels.sha256.json").write_text(
                json.dumps(data)
            )
            with self.assertRaisesRegex(ValueError, "conflicts with exact constraints"):
                lock.verify(root, wheels, root / "version.txt")

    def test_platform_mismatch_and_duplicate_lock_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheels, data = self.fixture(root)
            data["wheels"][0]["filename"] = "altgraph-0.17.5-py3-none-manylinux.whl"
            (root / "windows_agent/preview-wheels.sha256.json").write_text(
                json.dumps(data)
            )
            with self.assertRaisesRegex(ValueError, "architecture"):
                lock.verify(root, wheels, root / "platform.txt")
            data["wheels"][0] = dict(data["wheels"][1])
            (root / "windows_agent/preview-wheels.sha256.json").write_text(
                json.dumps(data)
            )
            with self.assertRaisesRegex(ValueError, "Duplicate locked wheel"):
                lock.verify(root, wheels, root / "duplicate.txt")

    def test_release_builds_must_use_offline_hash_checked_install(self):
        ps = (ROOT / "windows_agent/build.ps1").read_text()
        self.assertIn("param([string]$Version, [switch]$RequireLockedWheels)", ps)
        self.assertIn("if ($RequireLockedWheels)", ps)
        for flag in ("--no-index", "--only-binary=:all:", "--require-hashes",
                     "--find-links", "HAL_WINDOWS_HASHED_REQUIREMENTS"):
            self.assertIn(flag, ps)
        for workflow in ("windows-signing-candidate.yml",
                         "windows-public-preview-pages.yml"):
            config = (ROOT / ".github/workflows" / workflow).read_text()
            self.assertIn("windows_wheel_lock.py", config)
            self.assertIn("build.ps1", config)
            self.assertIn("-RequireLockedWheels", config)
            self.assertIn("HAL_WINDOWS_LOCKED_WHEELS=", config)
            self.assertIn("HAL_WINDOWS_HASHED_REQUIREMENTS=", config)


if __name__ == "__main__":
    unittest.main()
