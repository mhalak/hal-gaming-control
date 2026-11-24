"""Contract tests for real-wheel Windows license staging (no external downloads)."""
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/windows_preview_licenses.py"
spec = importlib.util.spec_from_file_location("windows_preview_licenses", SCRIPT)
lic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lic)


class FakeDistribution:
    def __init__(self, base: Path, name: str, version: str, *, with_license=True):
        self.version = version
        self.metadata = {"Name": name}
        self.base = base / name
        self.files = [PurePosixPath(f"{name}-{version}.dist-info/licenses/LICENSE.txt")]
        if with_license:
            path = self.locate_file(self.files[0])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name} actual license text", encoding="utf-8")

    def locate_file(self, name):
        return self.base / str(name)


class PreviewLicenseTests(unittest.TestCase):
    def fixture(self, root: Path):
        win = root / "windows_agent"
        (win / "dist").mkdir(parents=True)
        source = json.loads((ROOT / "windows_agent/preview-license-snapshot.json").read_text())
        (win / "preview-license-snapshot.json").write_text(json.dumps(source))
        python_home = root / "python"
        python_home.mkdir()
        (python_home / "LICENSE.txt").write_text("Real CPython license\n")
        distributions = {
            name: FakeDistribution(root / "wheels", name, version)
            for name, version in source["distributions"].items()
        }
        return source, python_home, distributions

    def test_stage_uses_installed_license_bytes_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected, python_home, wheels = self.fixture(root)
            result = lic.stage(
                root, python_home=python_home, python_version=expected["python"],
                find_distribution=lambda name: wheels[name],
            )
            self.assertEqual(result["distributions"], expected["distributions"])
            self.assertIs(result["legal_review_complete"], False)
            stage = root / "windows_agent/dist"
            for filename, expected_digest in result["files"].items():
                self.assertTrue(filename.startswith("licenses/"))
                self.assertEqual(hashlib.sha256((stage / filename).read_bytes()).hexdigest(),
                                 expected_digest)
            self.assertEqual(len(result["files"]), 1 + len(expected["distributions"]))
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                lic.stage(
                    root, python_home=python_home, python_version=expected["python"],
                    find_distribution=lambda name: wheels[name],
                )

    def test_version_drift_prevents_license_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected, python_home, wheels = self.fixture(root)
            wheels["cryptography"].version = "0.0.0"
            with self.assertRaisesRegex(ValueError, "version drift"):
                lic.stage(root, python_home=python_home,
                          python_version=expected["python"],
                          find_distribution=lambda name: wheels[name])
            self.assertFalse((root / "windows_agent/dist/licenses").exists())

    def test_missing_wheel_notice_and_cpython_license_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected, python_home, wheels = self.fixture(root)
            (python_home / "LICENSE.txt").unlink()
            with self.assertRaisesRegex(ValueError, "CPython LICENSE"):
                lic.stage(root, python_home=python_home,
                          python_version=expected["python"],
                          find_distribution=lambda name: wheels[name])
            (python_home / "LICENSE.txt").write_text("valid Python license")
            item = wheels["psutil"].locate_file(wheels["psutil"].files[0])
            item.unlink()
            with self.assertRaisesRegex(ValueError, "Missing/linked installed wheel license"):
                lic.stage(root, python_home=python_home,
                          python_version=expected["python"],
                          find_distribution=lambda name: wheels[name])


if __name__ == "__main__":
    unittest.main()
