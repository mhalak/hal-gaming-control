"""Regression tests for the repository's security CI contract."""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_security_scanners_and_permissions():
    workflow = load(".github/workflows/security-ci.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert {"push", "pull_request", "schedule"} <= set(workflow["on"])
    assert "pull_request_target" not in workflow["on"]
    jobs = workflow["jobs"]
    assert {"secrets", "python-sast", "python-dependencies", "powershell", "dependency-review"} <= set(jobs)
    assert all("permissions" not in job for job in jobs.values())
    assert all("continue-on-error" not in job for job in jobs.values())
    review = jobs["dependency-review"]
    assert review["if"] == "github.event_name == 'pull_request'"
    step = next(s for s in review["steps"] if "dependency-review-action@" in s.get("uses", ""))
    assert step["with"]["fail-on-severity"] == "high"
    assert step["with"]["warn-only"] == "false"


def test_codeql_and_action_pins():
    workflow = load(".github/workflows/codeql.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert {"push", "pull_request", "schedule"} <= set(workflow["on"])
    assert "pull_request_target" not in workflow["on"]
    assert workflow["jobs"]["analyze"]["permissions"] == {"contents": "read", "security-events": "write"}
    for name in ("security-ci.yml", "codeql.yml"):
        for job in load(f".github/workflows/{name}")["jobs"].values():
            assert "continue-on-error" not in job
            for step in job["steps"]:
                assert "continue-on-error" not in step
                if "uses" in step:
                    assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])


def test_dependabot_tracks_runtime_dependencies_and_actions():
    updates = load(".github/dependabot.yml")["updates"]
    assert {(item["package-ecosystem"], item["directory"]) for item in updates} >= {
        ("pip", "/windows_agent"), ("github-actions", "/")
    }
