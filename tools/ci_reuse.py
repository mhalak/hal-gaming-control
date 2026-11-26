"""Decide whether a main push can reuse fully verified PR CI evidence.

Only GitHub API metadata and immutable Git commit objects are evidence.
A missing/ambiguous response is a cache miss, never permission to skip CI.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

WORKFLOWS = {
    "HA integration CI": "ha-ci.yml",
    "Windows agent CI": "windows-ci.yml",
    "Direct MQTT runtime CI": "direct-mqtt-ci.yml",
    "Recorder coverage CI": "recorder-coverage-ci.yml",
    "HACS validation": "hacs-validation.yml",
    "Security CI": "security-ci.yml",
    "CodeQL": "codeql.yml",
    "Python code quality": "code-quality.yml",
}
REUSABLE = frozenset({
    "ha-ci.yml", "windows-ci.yml", "direct-mqtt-ci.yml",
    "recorder-coverage-ci.yml", "code-quality.yml",
})
MARKER = "CI tested commit "
SHA = re.compile(r"[0-9a-f]{40}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def commit_sha(value):
    require(isinstance(value, str) and SHA.fullmatch(value), "Invalid Git SHA")
    return value


def github_api(path):
    return json.loads(subprocess.check_output(
        ["gh", "api", "--method", "GET", path],
        text=True, timeout=20,
    ))


def merged_pr(api, repo, sha):
    candidates = api(f"repos/{repo}/commits/{sha}/pulls?per_page=100")
    require(isinstance(candidates, list) and 0 < len(candidates) < 100,
            "Missing or ambiguous associated PRs")
    matched = []
    for candidate in candidates:
        number = candidate["number"]
        require(type(number) is int and number > 0, "Invalid PR number")
        pr = api(f"repos/{repo}/pulls/{number}")
        if pr.get("merged") is True and pr.get("merge_commit_sha") == sha:
            matched.append(pr)
    require(len(matched) == 1, "No unique PR merged at this exact main SHA")
    pr = matched[0]
    require(pr["base"]["ref"] == "main", "PR did not target main")
    require(pr["base"]["repo"]["full_name"] == repo
            and pr["head"]["repo"]["full_name"] == repo,
            "Cross-repository PR evidence is not eligible")
    return pr


def associated_run(run, repo, pr):
    if run.get("event") != "pull_request":
        return False
    if run["repository"]["full_name"] != repo or run["head_repository"]["full_name"] != repo:
        return False
    return any(link["number"] == pr["number"]
               and link["head"]["sha"] == pr["head"]["sha"]
               and link["base"]["ref"] == "main"
               for link in run["pull_requests"])


def latest_runs(data, repo, pr):
    runs = data["workflow_runs"]
    require(data["total_count"] == len(runs), "Incomplete workflow result page")
    latest = {}
    for run in runs:
        name = run.get("name")
        if name not in WORKFLOWS or not associated_run(run, repo, pr):
            continue
        expected = ".github/workflows/" + WORKFLOWS[name]
        require(run["path"].split("@", 1)[0] == expected, "Unexpected workflow path")
        require(type(run["run_number"]) is int, "Invalid workflow run number")
        previous = latest.get(name)
        if previous is not None:
            require(run["run_number"] != previous["run_number"],
                    "Ambiguous duplicate workflow run")
        if previous is None or run["run_number"] > previous["run_number"]:
            latest[name] = run
    require(set(latest) == set(WORKFLOWS), "Not all eight PR workflows found")
    return latest


def tested_merge(latest, pr):
    markers = set()
    for run in latest.values():
        require(run["status"] == "completed" and run["conclusion"] == "success",
                "A required PR workflow is not green")
        require(run["updated_at"] <= pr["merged_at"], "CI was not complete at merge")
        title = run["display_title"]
        require(title.startswith(MARKER), "Missing tested-commit marker")
        tested = commit_sha(title[len(MARKER):])
        require(run["head_sha"] in (pr["head"]["sha"], tested), "Wrong PR run SHA")
        markers.add(tested)
    require(len(markers) == 1, "PR workflows did not test one merge commit")
    return markers.pop()


def verify_trees(api, repo, sha, before, head, tested):
    current = api(f"repos/{repo}/git/commits/{sha}")
    trial = api(f"repos/{repo}/git/commits/{tested}")
    require(current["sha"] == sha and trial["sha"] == tested, "Wrong Git object")
    parents = [p["sha"] for p in current["parents"]]
    require(parents in ([before], [before, head]), "Not a single PR merge/squash push")
    require([p["sha"] for p in trial["parents"]] == [before, head],
            "PR was tested on a different base or head")
    require(commit_sha(current["tree"]["sha"]) == commit_sha(trial["tree"]["sha"]),
            "Main tree differs from the tested merge tree")
    return current["tree"]["sha"]


def prove_reuse(api, repo, sha, before):
    commit_sha(sha)
    commit_sha(before)
    require(sha != before, "No new main commit")
    pr = merged_pr(api, repo, sha)
    head = commit_sha(pr["head"]["sha"])
    data = api(f"repos/{repo}/actions/runs?event=pull_request&head_sha={head}&per_page=100")
    latest = latest_runs(data, repo, pr)
    tested = tested_merge(latest, pr)
    tree = verify_trees(api, repo, sha, before, head, tested)
    evidence = ", ".join(f"{name} #{run['id']}" for name, run in sorted(latest.items()))
    return f"PR #{pr['number']}; merge {tested}; tree {tree}; runs: {evidence}"


def main():
    reuse = False
    try:
        require(os.environ["GITHUB_EVENT_NAME"] == "push"
                and os.environ["GITHUB_REF"] == "refs/heads/main", "Not a main push")
        evidence = prove_reuse(github_api, os.environ["GITHUB_REPOSITORY"],
                               os.environ["GITHUB_SHA"], os.environ["PUSH_BEFORE"])
        print(f"Verified identical PR CI: {evidence}")
        reuse = True
    except (ValueError, KeyError, TypeError, AttributeError, OSError,
            subprocess.SubprocessError) as err:
        print(f"Full CI required: {err}", file=sys.stderr)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"run_tests={'false' if reuse else 'true'}\n")


if __name__ == "__main__":
    main()
