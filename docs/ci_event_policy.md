# GitHub Actions event policy

The repository uses the same eight workflow names and required job/check names as before.

- **Pull requests:** every workflow runs on `pull_request` and uses a per-workflow, per-PR concurrency group. Newer revisions cancel in-progress obsolete runs of that workflow on the same PR. Do not bypass failing checks.
- **Default branch:** every workflow also runs on `push` **only for `main`**, retaining the post-merge safety gate. Each `main` run has a unique concurrency group (via `github.run_id`) and cannot cancel another main run.
- **Security:** CodeQL and Security CI retain their Tuesday schedule and manual `workflow_dispatch`. HACS validation and Python code quality retain manual dispatch. Each scheduled or manual run has its own group and is never canceled by an unrelated PR.
- **Check names:** unchanged. The code-quality workflow runs `tests/test_ci_event_policy.py` with its existing quality-gate tests to protect this contract.

## Backlog from earlier revisions

This policy affects **new runs evaluated against the revised workflow**. It does not retroactively cancel hundreds of already queued runs created under the old unlimited-push configuration. Owners with GitHub Actions write access can cancel obsolete runs on the Actions page; do not cancel runs from `main` or the latest PR revision. If a queued PR was created before this policy reached `main`, it may require one deliberate head update after this change is merged to receive the newer definition.

When reviewing feature PRs, merge only after all required checks pass on the **exact latest head SHA**. A passing old SHA or a still-queued check is not approval.

The same workflow also runs `tests/test_repository_identity.py`, which keeps the repository slug (`mhalak/hal-gaming-control`) and public product name (**HAL Gaming Control**) consistent and confines the previous names to the explicitly historical documents listed in that test.
