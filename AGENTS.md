# Repository working agreement

Follow this agreement for all human and agent contributions.

## Trunk-based development

- `main` is the only integration trunk and must remain buildable, tested and deployable.
- Start every change from current main. Keep branches and pull requests small and short-lived; aim to merge on the same day, ideally within hours. Do not keep a development branch open until an entire feature is complete.
- Track long-running work in GitHub issues. Split each issue into independently safe, testable increments. Reference the issue in each PR; close it only when the complete acceptance criteria are met.
- Integrate incremental work even when it has no visible benefit yet. Prefer functional, backwards-compatible scaffolding or shadow computation whose result does not affect production behavior.
- If incomplete behavior would be unsafe or incompatible, isolate it behind an internal, default-off gate, with no public UI, configuration, command or automatic activation path. Test both the disabled path and the new behavior. Remove temporary gates when the feature is completed.
- Do not ship incomplete code that changes existing accounting, triggers actions, breaks the protocol, or corrupts stored data. Preserve existing device IDs, HA entity IDs, configuration and safe defaults.
- New behavior needs regression tests in CI. Test experimental behavior in CI, not by keeping a permanent development branch. Physical Windows/HA acceptance can remain a follow-up issue for gated behavior; unvalidated behavior that can trigger real-world effects must stay disabled.
- Review the diff, run the required checks on the exact current candidate, and merge promptly once all applicable checks pass and the increment is safe. Never bypass red or missing required checks. If CI infrastructure fails, restore it or a trusted equivalent required CI runner first; do not confuse infrastructure errors with passing tests.
- After merge, delete the branch where permissions allow. Start the next increment from latest main.
- Deploy latest main using the normal deployment process. Independently version HA and Windows deployable changes and record the deployed commit. Never require a development branch for normal deployment.
- If a merged change fails in practice, open a fresh small fix branch from main, add regression tests, and merge the fix after green CI. Prefer fix-forward; revert or roll back only when needed to restore stability/safety and a timely safe fix is unavailable.

## Test-driven development (mandatory)

All feature work, behavior changes and bug fixes follow Red → Green → Refactor.

1. **Red:** Define expected behavior and acceptance criteria. Write automated tests before production code. Run the tests against the unmodified implementation and verify failure for the intended missing behavior or defect, not an unrelated setup error.
2. **Green:** Implement the smallest production change that satisfies the tests. Run targeted tests and the relevant regression suites.
3. **Refactor:** Improve the implementation and tests without changing verified behavior; rerun tests and quality checks.

- Keep implementation and corresponding tests in the same PR. Separate RED and GREEN commits are encouraged for traceability; never merge failing tests into main.
- Cover positive, negative and boundary cases, including regression tests for every bug fix, and verify device isolation and safety-relevant behavior where applicable.
- Record actual RED/GREEN evidence in the PR description: commands, expected failure, actual results and commit or CI links. Report blockers; do not claim execution that did not occur.
- Never weaken assertions, skip tests or remove regression cases to obtain green results. Documentation-only changes do not require artificial failing tests.

## Code quality targets

- Minimum line coverage: 90% independently for the HA integration and Windows agent production Python code. Measure branch coverage separately; no numeric branch threshold has been approved.
- Maximum Radon cyclomatic complexity: C (20) per function, async function, method or nested function, not an average.
- Include production entry points and runtime modules; exclude tests and generated output. Combine Linux and Windows execution evidence for the agent without averaging percentages.
- Measure and publish the initial baseline before enabling automated enforcement. Track existing debt, correct it through tested increments, then enforce the targets as required CI checks. Until that point, report actual noncompliance and do not increase debt. Do not lower the targets or hide violations with exclusions or waivers.
- Require green applicable CI and review before merge. Configure branch protection and required quality checks as they become available. No claim that a policy alone provides technical enforcement.

## Definition of a mergeable increment

1. The existing supported behavior remains intact and the candidate builds.
2. New behavior and its test-first tests are in the same PR, with actual RED/GREEN evidence; default-off features are demonstrably unreachable in normal operation.
3. Required CI checks pass; any safety-sensitive enabled behavior has appropriate evidence.
4. The remaining feature work is recorded in an issue, not left in the branch.
5. Deployable component versions, relevant docs and migration constraints are updated.

All code, documentation, PRs and issues are written in English.
