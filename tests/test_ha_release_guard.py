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
        paths = (
            ".github/workflows/ha-ci.yml", ".github/workflows/windows-ci.yml",
            ".github/workflows/direct-mqtt-ci.yml", ".github/workflows/recorder-coverage-ci.yml",
            ".github/workflows/hacs-validation.yml", ".github/workflows/security-ci.yml",
            ".github/workflows/codeql.yml", ".github/workflows/code-quality.yml",
        )
        self.assertEqual(module.REQUIRED_WORKFLOWS, frozenset(paths))
        runs = [{"path": path, "name": "Any display name", "head_branch": "main",
                 "head_sha": SHA, "event": "push", "status": "completed",
                 "conclusion": "success", "run_number": 4, "run_attempt": 1}
                for path in paths]
        module.ci_gate(runs, SHA)
        with self.assertRaises(ValueError):
            module.ci_gate(runs[:-1], SHA)
        for field, value in (("conclusion", "failure"), ("head_sha", "b" * 40),
                             ("status", "queued"), ("event", "pull_request")):
            modified = [dict(r, **{field: value}) if r["path"] == ".github/workflows/hacs-validation.yml" else r
                        for r in runs]
            with self.assertRaises(ValueError):
                module.ci_gate(modified, SHA)

    def test_gate_accepts_actual_run_name_and_rejects_wrong_workflow_path(self):
        # Selected fields from the eight main push runs for the failed 0.19.0
        # publication; run-name is not the workflow's stable identity.
        runs = json.loads("[\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/hacs-validation.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 1189,\n    \"run_attempt\": 1\n  },\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/recorder-coverage-ci.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 1189,\n    \"run_attempt\": 1\n  },\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/security-ci.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 935,\n    \"run_attempt\": 1\n  },\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/codeql.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 935,\n    \"run_attempt\": 1\n  },\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/ha-ci.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 1189,\n    \"run_attempt\": 1\n  },\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/code-quality.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 1159,\n    \"run_attempt\": 1\n  },\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/windows-ci.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 1189,\n    \"run_attempt\": 1\n  },\n  {\n    \"name\": \"CI tested commit 0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"path\": \".github/workflows/direct-mqtt-ci.yml\",\n    \"head_branch\": \"main\",\n    \"head_sha\": \"0b4a383155720921898d709b56f3049d4f208c6c\",\n    \"event\": \"push\",\n    \"status\": \"completed\",\n    \"conclusion\": \"success\",\n    \"run_number\": 1189,\n    \"run_attempt\": 1\n  }\n]")
        sha = "0b4a383155720921898d709b56f3049d4f208c6c"
        module.ci_gate(runs, sha)
        for field, value in (("path", ".github/workflows/unrelated.yml"),
                             ("path", None), ("head_branch", "feature"),
                             ("head_sha", "b" * 40), ("event", "pull_request"),
                             ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(field=field, value=value):
                modified = [dict(runs[0], **{field: value}), *runs[1:]]
                with self.assertRaises(ValueError):
                    module.ci_gate(modified, sha)
        for field, value in (("run_number", None), ("run_attempt", True),
                             ("run_attempt", 0)):
            modified = [dict(runs[0], **{field: value}), *runs[1:]]
            with self.assertRaises(ValueError):
                module.ci_gate(modified, sha)
        conflicting = dict(runs[0], conclusion="failure")
        with self.assertRaises(ValueError):
            module.ci_gate([*runs, conflicting], sha)
        newest = dict(runs[0], run_number=runs[0]["run_number"] + 1,
                      conclusion="failure")
        for candidate in ([*runs, newest], [newest, *runs]):
            with self.assertRaises(ValueError):
                module.ci_gate(candidate, sha)
        retry = dict(runs[0], run_attempt=runs[0]["run_attempt"] + 1,
                     status="in_progress", conclusion=None)
        for candidate in ([*runs, retry], [retry, *runs]):
            with self.assertRaises(ValueError):
                module.ci_gate(candidate, sha)

    def test_marketplace_release_not_hidden_as_prerelease(self):
        workflow = (SOURCE.parents[1] / ".github/workflows/publish-ha-preview.yml").read_text(encoding="utf-8")
        self.assertIn("startsWith(github.event.comment.body, '/publish-ha-release ')", workflow)
        self.assertIn("github.event.issue.number == 189", workflow)
        self.assertIn("github.event.comment.user.login == 'mhalak'", workflow)
        self.assertIn('RELEASE_COMMAND: ${{ github.event.comment.body }}', workflow)
        self.assertIn('[[ "$RELEASE_COMMAND" == "/publish-ha-release $VERSION" ]]', workflow)
        self.assertNotIn("github.event.comment.body == '/publish-ha-release 0.12.1'", workflow)
        self.assertIn('gh release edit "$VERSION"', workflow)
        self.assertIn('--prerelease=false', workflow)
        self.assertIn('git diff --quiet "refs/tags/$VERSION" HEAD -- custom_components/hal_gaming_control', workflow)
        self.assertNotIn('--prerelease --latest=false', workflow)

    def test_preview_notes_never_promote_windows_or_deploy(self):
        notes = module.build_notes("0.12.1", "A fix.", SHA)
        for fragment in ("source-only development preview", "0.12.1", "issue #56", "Redownload"):
            self.assertIn(fragment, notes)
        self.assertIn("Unified MQTT v3", notes)
        self.assertNotIn("option must be enabled", notes)
        self.assertIn("re-enrollment.\n\n**Deployment HOLD:**", notes)
        with self.assertRaises(ValueError):
            module.build_notes("0.12.1", "A fix.", "not-a-sha")


if __name__ == "__main__":
    unittest.main()
