"""Regression and safety tests for the isolated Windows Pages distribution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "windows_download_page.py"
spec = importlib.util.spec_from_file_location("windows_download_page", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SHA = "a" * 40
VERSION = "0.4.3"


class PagesDistributionTests(unittest.TestCase):
    def source(self, root):
        (root / "windows_agent" / "dist" / "SmartHouseGamingControl").mkdir(parents=True)
        (root / "windows_agent" / "dist" / "SmartHouseGamingUpdater").mkdir(parents=True)
        (root / "release.json").write_text(json.dumps({
            "release": "Preview 40", "windows_agent": VERSION, "home_assistant": "0.14.1"
        }), encoding="utf-8")
        win = root / "windows_agent"
        for name, exe in (("SmartHouseGamingControl", "SmartHouseGamingControl.exe"),
                          ("SmartHouseGamingUpdater", "SmartHouseGamingUpdater.exe")):
            (win / "dist" / name / exe).write_bytes(b"fake PE placeholder, NOT signed")
        service = win / "dist" / "SmartHouseGamingControl"
        (service / "version.txt").write_text(VERSION + "\n", encoding="utf-8")
        (service / "build-info.json").write_text(json.dumps({
            "component": "windows_agent", "version": VERSION, "commit": SHA
        }), encoding="utf-8")
        for path in mod.SCRIPTS:
            (win / path).write_text("placeholder\n", encoding="utf-8")
        (root / "LICENSE").write_text("Project MIT license text\n", encoding="utf-8")
        (root / "THIRD_PARTY_NOTICES.md").write_text(
            "Technical inventory; unresolved items remain NOT CONFIRMED.\n", encoding="utf-8"
        )
        audit = json.loads((ROOT / "windows_agent/preview-license-snapshot.json").read_text())
        (win / "preview-license-snapshot.json").write_text(json.dumps(audit))
        license_dir = win / "dist" / "licenses"
        license_dir.mkdir()
        payloads = {"licenses/Python/LICENSE.txt": b"CPython copyright and license"}
        for name in audit["distributions"]:
            payloads[f"licenses/{name}/LICENSE.txt"] = (name + " own upstream license").encode()
        hashes = {}
        for name, content in payloads.items():
            target = win / "dist" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        (license_dir / "manifest.json").write_text(json.dumps({
            "schema": 1, "python": audit["python"],
            "distributions": audit["distributions"], "files": hashes,
            "legal_review_complete": False,
        }))

    def test_page_archive_contains_both_exes_hashes_and_honest_disclaimer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source(root)
            site = root / "page"
            manifest = mod.build(root, site, SHA)
            archive = site / "windows" / VERSION / manifest["archive"]
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as zipped:
                self.assertTrue(set(mod.OWNED).issubset(zipped.namelist()))
                self.assertIn("install.ps1", zipped.namelist())
                self.assertIn("config.example.yaml", zipped.namelist())
                self.assertIn("SmartHouseGamingControl/build-info.json", zipped.namelist())
                self.assertIn("LICENSE", zipped.namelist())
                self.assertIn("THIRD_PARTY_NOTICES.md", zipped.namelist())
                self.assertIn("licenses/manifest.json", zipped.namelist())
                self.assertIn("licenses/Python/LICENSE.txt", zipped.namelist())
                self.assertIn("licenses/pyinstaller/LICENSE.txt", zipped.namelist())
            self.assertEqual(manifest["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertIn(manifest["sha256"], (archive.parent / "SHA256SUMS.txt").read_text())
            self.assertEqual(manifest["signature_status"], "NotSigned")
            self.assertIs(manifest["trusted_for_installation"], False)
            for page in (site / "index.html", archive.parent / "index.html"):
                html = page.read_text()
                self.assertIn("UNSIGNED DEVELOPMENT PREVIEW", html)
                self.assertIn("Smart App Control", html)
                self.assertIn(manifest["sha256"], html)
                self.assertIn(manifest["archive"], html)
            self.assertNotIn("hal_gaming_control", archive.read_bytes().decode("latin1"))

    def test_fail_closed_invalid_sha_version_and_build_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source(root)
            with self.assertRaisesRegex(ValueError, "source SHA"):
                mod.build(root, root / "badsha", "not-a-sha")
            (root / "windows_agent" / "dist" / "SmartHouseGamingControl" / "build-info.json").write_text(
                json.dumps({"component": "windows_agent", "version": VERSION, "commit": "b" * 40})
            )
            with self.assertRaisesRegex(ValueError, "provenance"):
                mod.build(root, root / "badsource", SHA)
            (root / "release.json").write_text(json.dumps(
                {"windows_agent": "0.4.4", "home_assistant": "0.14.1"}
            ))
            with self.assertRaisesRegex(ValueError, "version.txt"):
                mod.build(root, root / "badversion", SHA)

    def test_fail_closed_missing_exe_and_duplicate_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source(root)
            site = root / "published"
            mod.build(root, site, SHA)
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                mod.build(root, site, SHA)
            (root / "windows_agent" / "dist" / "SmartHouseGamingUpdater" /
             "SmartHouseGamingUpdater.exe").unlink()
            with self.assertRaisesRegex(ValueError, "Missing project-owned EXE"):
                mod.build(root, root / "noexe", SHA)

    def test_fail_closed_missing_and_tampered_license_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source(root)
            manifest_path = root / "windows_agent/dist/licenses/manifest.json"
            (root / "THIRD_PARTY_NOTICES.md").unlink()
            with self.assertRaisesRegex(ValueError, "Missing project license/notice"):
                mod.build(root, root / "missing-notice", SHA)
            (root / "THIRD_PARTY_NOTICES.md").write_text("Unresolved audit.\\n")
            license_path = root / "windows_agent/dist/licenses/Python/LICENSE.txt"
            license_path.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "modified upstream license"):
                mod.build(root, root / "tampered", SHA)
            license_path.write_bytes(b"CPython copyright and license")
            data = json.loads(manifest_path.read_text())
            data["distributions"]["cryptography"] = "0.0.0"
            manifest_path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "audited versions"):
                mod.build(root, root / "wrong-version", SHA)

    def test_private_wheel_inventory_is_version_constrained_and_unpublished(self):
        constraints = (ROOT / "windows_agent/preview-constraints.txt").read_text()
        pins = [line.strip() for line in constraints.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(len(pins), 19)
        self.assertTrue(all(re.fullmatch(
            r"[a-zA-Z0-9._-]+==[0-9][^; ]*(?:; sys_platform == 'win32')?",
            pin) for pin in pins))
        names = [pin.split("==")[0].lower().replace("_", "-") for pin in pins]
        self.assertEqual(len(set(names)), 19)
        candidate = (ROOT / ".github/workflows/windows-signing-candidate.yml").read_text()
        self.assertIn("windows_wheel_lock.py", candidate)
        self.assertIn("preview-audit-requirements.txt", candidate)
        self.assertIn("preview-constraints.txt", candidate)
        self.assertIn("pip download --only-binary=:all:", candidate)
        self.assertIn("HAL_WINDOWS_HASHED_REQUIREMENTS=", candidate)
        self.assertIn("HAL_WINDOWS_LOCKED_WHEELS=", candidate)
        self.assertIn("build.ps1 -RequireLockedWheels", candidate)
        self.assertNotIn("contents: write", candidate)
        self.assertNotIn("pages: write", candidate)
        roots = (ROOT / "windows_agent/preview-audit-requirements.txt").read_text()
        self.assertIn("-r requirements-dev.txt", roots)
        self.assertIn("pyinstaller>=6,<7", roots)

    def test_private_candidate_validates_real_licensed_zip_without_publishing_it(self):
        cfg = (ROOT / ".github/workflows/windows-signing-candidate.yml").read_text()
        self.assertIn("PIP_CONSTRAINT:", cfg)
        self.assertIn("preview-constraints.txt", cfg)
        self.assertIn("windows_preview_licenses.py", cfg)
        self.assertIn("windows_download_page.py", cfg)
        self.assertIn("PRIVATE UNSIGNED preview staging SUCCESS", cfg)
        self.assertIn("This temporary ZIP is not uploaded or published", cfg)
        self.assertIn("python-version: '3.12.10'", cfg)
        self.assertNotIn("deploy-pages@", cfg)
        self.assertNotIn("pages: write", cfg)
        self.assertNotIn("contents: write", cfg)
        self.assertNotIn("gh release create", cfg)
        self.assertNotIn("upload-pages-artifact@", cfg)
        self.assertIn("retention-days: 1", cfg)

    def test_workflow_is_owner_only_manual_and_never_creates_ha_releases(self):
        cfg = (ROOT / ".github/workflows/windows-public-preview-pages.yml").read_text()
        # GitHub rejects a workflow with malformed ${{ ... }} expressions
        # before it can run any jobs; require exactly matched delimiters.
        expressions = re.findall(r"\$\{\{[^\n{}]+\}\}", cfg)
        self.assertEqual(cfg.count("${{"), len(expressions))
        self.assertGreaterEqual(len(expressions), 19)
        assert "workflow_dispatch:" in cfg
        for forbidden in ("issue_comment:", "pull_request:", "  push:", "gh release create",
                          "gh release edit", "gh release upload", "git push", "SignPath"):
            if forbidden == "SignPath":  # Not mentioned in signed-code calls.
                self.assertNotIn("submit-signing-request", cfg)
            else:
                self.assertNotIn(forbidden, cfg)
        for required in (
                "github.actor == 'mhalak'", "github.ref == 'refs/heads/main'",
                "github.repository == 'mhalak/hal-gaming-control'",
                "inputs.authorization == 'PUBLISH_UNSIGNED_WINDOWS_PREVIEW'",
                "DO_NOT_PUBLISH", "needs.build.result == 'success'",
                "ha_release_guard.py gate", "releases/latest",
                "windows_preview_licenses.py", "preview-constraints.txt",
                "windows_wheel_lock.py", "-RequireLockedWheels",
                "deploy-pages@", "upload-pages-artifact@", "Get-AuthenticodeSignature",
                "NotSigned", "contents: read", "pages: write", "id-token: write"):
            self.assertIn(required, cfg)
        self.assertNotIn("contents: write", cfg)
        self.assertNotIn("github.event.comment", cfg)
        # Version declarations are independent of the read-only Pages workflow.
        declaration = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "custom_components/hal_gaming_control/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(declaration["home_assistant"], manifest["version"])
        for component in ("home_assistant", "windows_agent"):
            self.assertRegex(declaration[component], r"^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")
        self.assertNotIn("sync-ha", cfg)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", SHA))


if __name__ == "__main__":
    unittest.main()
