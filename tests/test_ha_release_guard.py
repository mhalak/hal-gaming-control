"""Regression checks for HA release identity, main CI, and preview safety."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "ha_release_guard.py"
spec = importlib.util.spec_from_file_location("ha_release_guard", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = "a" * 40


class HaReleaseTests(unittest.TestCase):
    def test_release_notes_match_component_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "custom_components/hal_gaming_control").mkdir(parents=True)
            (root / "docs").mkdir()
            (root / "release.json").write_text(json.dumps({"home_assistant": "0.12.1", "windows_agent": "0.4.0"}))
            path = root / "custom_components/hal_gaming_control/manifest.json"
            path.write_text(json.dumps({"domain": "hal_gaming_control", "version": "0.12.1"}))
            (root / "docs/ha_releases.md").write_text("## 0.12.1 — Fix\n\nFixed HA.\n\n## Preview 21\nOlder.\n")
            self.assertEqual(module.version_and_notes(root), ("0.12.1", "Fixed HA."))
            path.write_text(json.dumps({"domain": "hal_gaming_control", "version": "0.12.0"}))
            with self.assertRaises(ValueError):
                module.version_and_notes(root)

    def test_gate_requires_exact_eight_successful_main_pushes(self):
        runs = [{"name": name, "head_branch": "main", "head_sha": SHA, "event": "push",
                 "status": "completed", "conclusion": "success", "run_number": 4}
                for name in module.REQUIRED_WORKFLOWS]
        module.ci_gate(runs, SHA)
        with self.assertRaises(ValueError):
            module.ci_gate(runs[:-1], SHA)
        for field, value in (("conclusion", "failure"), ("head_sha", "b" * 40),
                             ("status", "queued"), ("event", "pull_request")):
            modified = [dict(r, **{field: value}) if r["name"] == "HACS validation" else r
                        for r in runs]
            with self.assertRaises(ValueError):
                module.ci_gate(modified, SHA)

    def test_preview_notes_never_promote_windows_or_deploy(self):
        notes = module.build_notes("0.12.1", "A fix.", SHA)
        for fragment in ("source-only prerelease", "0.12.1", "issue #56", "Redownload"):
            self.assertIn(fragment, notes)
        with self.assertRaises(ValueError):
            module.build_notes("0.12.1", "A fix.", "not-a-sha")


if __name__ == "__main__":
    unittest.main()
