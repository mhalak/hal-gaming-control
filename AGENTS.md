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

## Cross-component MQTT protocol contracts (mandatory)

- The **source-controlled, versioned wire examples** in [tests/contracts](tests/contracts/README.md) are the shared contract for messages crossing Windows ↔ Home Assistant. They are not generated at test time from either component's implementation.
- Every new or changed MQTT message shape, topic, field meaning or version requires a **Windows production publisher/serializer test** and a **Home Assistant production decoder/consumer test** against the *same* example. Test the actual end-user consumer path, not just a helper returning synthetic parsed state; for application enrollment, test MQTT → HA Options Flow → Add/Save.
- **Never silently rewrite an old-version contract fixture to make a change green.** A breaking format gets a new versioned fixture. Keep the old samples as regression gates for supported versions; if deliberately retired, update the explicit clean-cut migration, negative compatibility tests and release notes.
- Verify full field names/types, device isolation, freshness, retention, malformed/unknown payload rejection and that no command can be fabricated by read-only messages. Dynamic fields can be normalized only *after* checking their valid bounds.
- Ensure Windows and HA CI execute their respective contract cases in every relevant PR. A green Windows publisher test alone or HA consumer test alone is **not** evidence of protocol compatibility.

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

## Agent model and token disclosure in pull requests

- Every PR created or worked on by an AI agent must contain an `## Agent usage` section in the **PR description**, not only in a comment. Keep it updated after additional implementation, review or rework and before merge.
- Identify each contributing agent and the **exact model identifier** used. If multiple models or agents contributed, report each separately.
- Report the tokens consumed **for work on this PR**, using actual usage telemetry where available: input tokens, output tokens and total tokens. Add cached or reasoning token details only when the provider exposes them, and avoid double-counting them in the total.
- Include the measurement source and scope when relevant. Do not present a full conversation/session total as a PR-only total unless all of that usage belongs to the PR.
- If token usage telemetry is unavailable, **make a best-effort estimate** of input, output and total tokens attributable to this PR, based on available context size, interaction/tool-call counts, or other reasonable evidence. Mark every estimated number or range **`estimated`**, briefly describe the assumptions and uncertainty, and use sensible rounding rather than false precision. Prefer a range if uncertainty is substantial.
- Label measured values **`measured`** and include the telemetry source; label estimates **`estimated`** and describe the estimation basis. Never present estimates as measurements or invent measured figures. If a precise model identifier is not exposed, mark the model `unavailable` rather than guessing.

All code, documentation, PRs and issues are written in English.
