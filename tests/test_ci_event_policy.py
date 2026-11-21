"""Regression checks for CI policy: once per PR revision; all main pushes."""
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ["code-quality.yml","codeql.yml","direct-mqtt-ci.yml","ha-ci.yml","hacs-validation.yml","recorder-coverage-ci.yml","security-ci.yml","windows-ci.yml"]
GROUP = "  group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}"
CANCEL = "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}"


@pytest.mark.parametrize("filename", WORKFLOWS)
def test_main_and_pr_checks_have_distinct_event_policies(filename):
    cfg = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
    events = cfg.split("\non:\n", 1)[1].split("\nconcurrency:\n", 1)[0].splitlines()
    assert events[:3] == ["  push:", "    branches: [main]", "  pull_request:"]
    assert "on: [" not in cfg
    assert GROUP in cfg
    assert CANCEL in cfg
    assert cfg.count("\nconcurrency:\n") == 1


@pytest.mark.parametrize("filename", ["codeql.yml", "security-ci.yml"])
def test_scheduled_security_checks_still_run(filename):
    cfg = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
    events = cfg.split("\non:\n", 1)[1].split("\nconcurrency:\n", 1)[0].splitlines()
    assert "  schedule:" in events
    assert "  workflow_dispatch:" in events


@pytest.mark.parametrize("filename", ["code-quality.yml", "hacs-validation.yml"])
def test_manual_quality_checks_still_available(filename):
    cfg = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
    events = cfg.split("\non:\n", 1)[1].split("\nconcurrency:\n", 1)[0].splitlines()
    assert "  workflow_dispatch:" in events
