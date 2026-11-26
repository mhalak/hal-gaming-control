"""CI reuse accepts only complete, immutable same-tree PR evidence."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_reuse", ROOT / "tools/ci_reuse.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)
REPO = "owner/repo"
MAIN, BASE, HEAD, MERGE, TREE = (c * 40 for c in "abcde")


@pytest.fixture
def evidence():
    pr = {
        "number": 7, "merged": True, "merge_commit_sha": MAIN,
        "merged_at": "2026-11-26T12:05:00Z",
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
    }
    runs = [{
        "name": name, "path": ".github/workflows/" + path,
        "id": number, "run_number": 2, "event": "pull_request",
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
        "head_sha": HEAD, "display_title": ci.MARKER + MERGE,
        "pull_requests": [{"number": 7, "head": {"sha": HEAD},
                           "base": {"ref": "main"}}],
        "status": "completed", "conclusion": "success",
        "updated_at": "2026-11-26T12:04:00Z",
    } for number, (name, path) in enumerate(ci.WORKFLOWS.items(), 1)]
    prefix = f"repos/{REPO}"
    return {
        f"{prefix}/commits/{MAIN}/pulls?per_page=100": [{"number": 7}],
        f"{prefix}/pulls/7": pr,
        f"{prefix}/actions/runs?event=pull_request&head_sha={HEAD}&per_page=100":
            {"workflow_runs": runs, "total_count": len(runs)},
        f"{prefix}/git/commits/{MAIN}":
            {"sha": MAIN, "tree": {"sha": TREE}, "parents": [{"sha": BASE}]},
        f"{prefix}/git/commits/{MERGE}":
            {"sha": MERGE, "tree": {"sha": TREE},
             "parents": [{"sha": BASE}, {"sha": HEAD}]},
    }


def prove(evidence):
    return ci.prove_reuse(evidence.__getitem__, REPO, MAIN, BASE)


def runs(evidence):
    return evidence[f"repos/{REPO}/actions/runs?event=pull_request&head_sha={HEAD}&per_page=100"]


def test_all_eight_same_tree_allow_squash_reuse(evidence):
    result = prove(evidence)
    assert "PR #7" in result and MERGE in result and TREE in result
    assert all(name in result for name in ci.WORKFLOWS)


def test_regular_merge_is_also_eligible(evidence):
    evidence[f"repos/{REPO}/git/commits/{MAIN}"]["parents"].append({"sha": HEAD})
    assert TREE in prove(evidence)


@pytest.mark.parametrize("field,value", [
    ("conclusion", "failure"), ("status", "in_progress"),
    ("event", "push"), ("display_title", "Old workflow"),
    ("display_title", ci.MARKER + "f" * 40),
    ("head_sha", "f" * 40), ("pull_requests", []),
    ("path", ".github/workflows/unrelated.yml"),
    ("head_repository", {"full_name": "fork/repo"}),
    ("updated_at", "2026-11-26T12:06:00Z"),
])
def test_any_invalid_run_blocks_reuse(evidence, field, value):
    runs(evidence)["workflow_runs"][0][field] = value
    with pytest.raises(ValueError):
        prove(evidence)


def test_newer_failed_run_cannot_be_hidden_by_older_success(evidence):
    data = runs(evidence)
    failed = deepcopy(data["workflow_runs"][0])
    failed.update(run_number=3, conclusion="failure", id=999)
    data["workflow_runs"].append(failed)
    data["total_count"] += 1
    with pytest.raises(ValueError):
        prove(evidence)


@pytest.mark.parametrize("problem", ["missing", "truncated", "duplicate"])
def test_partial_or_ambiguous_results_block_reuse(evidence, problem):
    data = runs(evidence)
    if problem == "missing":
        data["workflow_runs"].pop()
        data["total_count"] -= 1
    elif problem == "truncated":
        data["total_count"] += 1
    else:
        data["workflow_runs"].append(deepcopy(data["workflow_runs"][0]))
        data["total_count"] += 1
    with pytest.raises(ValueError):
        prove(evidence)


@pytest.mark.parametrize("problem", ["tree", "base", "head", "push", "fork", "unmerged", "target"])
def test_wrong_git_objects_or_pr_provenance_block_reuse(evidence, problem):
    trial = evidence[f"repos/{REPO}/git/commits/{MERGE}"]
    pr = evidence[f"repos/{REPO}/pulls/7"]
    if problem == "tree":
        trial["tree"]["sha"] = "f" * 40
    elif problem == "base":
        trial["parents"][0]["sha"] = "f" * 40
    elif problem == "head":
        trial["parents"][1]["sha"] = "f" * 40
    elif problem == "push":
        evidence[f"repos/{REPO}/git/commits/{MAIN}"]["parents"][0]["sha"] = "f" * 40
    elif problem == "fork":
        pr["head"]["repo"]["full_name"] = "fork/repo"
    elif problem == "unmerged":
        pr["merged"] = False
    else:
        pr["base"]["ref"] = "other"
    with pytest.raises(ValueError):
        prove(evidence)


@pytest.mark.parametrize("fail", [False, True])
def test_cli_defaults_to_full_ci_on_missing_api_evidence(evidence, monkeypatch, tmp_path, fail):
    output = tmp_path / "output"
    for key, value in {
        "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": REPO, "GITHUB_SHA": MAIN, "PUSH_BEFORE": BASE,
        "GITHUB_OUTPUT": str(output),
    }.items():
        monkeypatch.setenv(key, value)
    if fail:
        evidence.clear()
    monkeypatch.setattr(ci, "github_api", evidence.__getitem__)
    ci.main()
    assert output.read_text() == ("run_tests=true\n" if fail else "run_tests=false\n")


@pytest.mark.parametrize("filename", ci.WORKFLOWS.values())
def test_workflow_reuse_is_main_only_and_explicit(filename):
    cfg = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
    assert "run-name: 'CI tested commit " + "$" + "{{ github.sha }}'" in cfg
    if filename in ci.REUSABLE:
        assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in cfg
        assert "uses: ./.github/workflows/ci-reuse.yml" in cfg
        assert "needs.reuse.outputs.run_tests != 'false'" in cfg
        assert "github.event_name != 'push'" in cfg
    else:
        assert "ci-reuse.yml" not in cfg


def test_release_guard_still_requires_exact_main_results():
    cfg = (ROOT / ".github/workflows/publish-ha-preview.yml").read_text(encoding="utf-8")
    assert '-f head_sha="$SOURCE_SHA" -f event=push' in cfg
    assert '[[ "$SOURCE_SHA" == "$MAIN_SHA" ]]' in cfg
    guard = (ROOT / "tools/ha_release_guard.py").read_text(encoding="utf-8")
    assert 'run.get("event") != "push"' in guard
