# Automated security checks

Security CI and CodeQL run for pull requests, pushes to main, weekly schedules and manual dispatch. All new action references are pinned to full commit SHAs. Standard public GitHub-hosted runners and open-source tools are used; no paid services, private signing material, write access to source or privileged PR triggers are required. Only the CodeQL job needs security-events: write to publish analysis.

| Check | Scope and policy |
| --- | --- |
| Gitleaks | Checked-out Git history; any detected secret fails. Findings are fully redacted, with no raw secret artifact. |
| Bandit | HA and Windows Python production code; high severity fails, medium is reported for review. |
| pip-audit | Resolved Windows production dependencies and HA integration-specific requirements; any known vulnerability fails because uniform severity is not available. Does not audit the full HA core or every possible version allowed by a requirement range. |
| PSScriptAnalyzer | Production Windows PowerShell scripts; errors fail, warnings require review. |
| Dependency Review | PR dependency changes, including development dependencies; high/critical vulnerabilities fail. Requires dependency graph availability. |
| CodeQL | Python security-extended analysis uploaded to GitHub code scanning. Successful analysis alone does not mean no alerts. |

Dependabot proposes weekly Python and GitHub Actions updates. Existing native secret scanning and vulnerability reporting are complementary. Before merging, review medium findings, remediate high/critical findings and secrets, and do not add blanket suppressions. Existing findings may make the first baseline red; fix them with focused tests and reviewed patches rather than disabling checks. A scanner cannot prove absence of vulnerabilities.

## Repository administration (required separately)

Enable the dependency graph, secret scanning, push protection and private vulnerability reporting where available. Use advanced CodeQL workflow setup rather than competing default setup. Configure branch protection or rulesets to require the applicable passing CI jobs and CodeQL code-scanning results at high/critical security severity, and prevent unchecked merges. This workflow alone cannot configure those repository settings or verify alert-based merge protection.

## Product-specific verification

Cover unauthorized/cross-device MQTT commands, malformed/stale/replayed messages, command injection, update signature and archive tampering, traversal, service/task privileges, private-data logging and unintended terminate/lock in targeted TDD regression tests. Static scanners do not substitute for authenticated broker authorization, native Windows acceptance, signed distribution or E2E tests. Test with synthetic data and authorized disposable sessions only. Never disable Windows security features for installation.
