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

    def test_workflow_is_owner_only_manual_and_never_creates_ha_releases(self):
        cfg = (ROOT / ".github/workflows/windows-public-preview-pages.yml").read_text()
        # GitHub rejects a workflow with malformed ${{ ... }} expressions
        # before it can run any jobs; require exactly matched delimiters.
        expressions = re.findall(r"\$\{\{[^\n{}]+\}\}", cfg)
        self.assertEqual(cfg.count("${{"), len(expressions))
        self.assertEqual(len(expressions), 19)
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
                "deploy-pages@", "upload-pages-artifact@", "Get-AuthenticodeSignature",
                "NotSigned", "contents: read", "pages: write", "id-token: write"):
            self.assertIn(required, cfg)
        self.assertNotIn("contents: write", cfg)
        self.assertNotIn("github.event.comment", cfg)
        # No new HA version or Windows-only GitHub release tag.
        declaration = json.loads((ROOT / "release.json").read_text())
        self.assertEqual(declaration["home_assistant"], "0.14.1")
        self.assertEqual(declaration["windows_agent"], "0.4.3")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", SHA))


if __name__ == "__main__":
    unittest.main()
