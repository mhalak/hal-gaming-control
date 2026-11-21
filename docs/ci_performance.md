# CI latency and critical-path optimization

This repo keeps eight independent GitHub Actions workflow checks, with the
same required unit/integration/security tests, same Windows and Linux OS
coverage, 90% line-coverage minimum and C-complexity ceiling. A green run
on **the exact proposed commit** is required before merging.

## Baseline (2026-11-21)

Measured from the first to the last timestamp in GitHub Actions job logs
for PR #63 (SHA `3fe22acebd113cc9b7b3382622667db0a7fd6e35`);
these are **job durations** including checkout and installation, not the
overall workflow wall clock or queue delay.

| Critical job | Approx. baseline elapsed |
| --- | ---: |
| Python code quality / ha-coverage | 94 s |
| HA integration CI / runtime | 69 s |
| Python code quality / Windows coverage data (Windows) | 66 s |
| Windows agent CI / Windows | 57 s |
| CodeQL | 46 s |
| Security CI / Gitleaks | 44 s |
| Python code quality / Windows coverage combine | 11 s after matrix |

The HA coverage job spent about 56 seconds installing dependencies.
Therefore its bottleneck was preparation, not pytest. The Windows coverage
combine is the **only intentional dependency edge** among these stages:
both platform measurements must be present before computing the aggregate
coverage and enforcing the >=90% threshold.

## Initial optimizations

- Pin the third-party `setup-uv` action to a reviewed commit and pin the
  `uv` executable version. Use `uv pip install --system` only in jobs that
  spent material time installing Python test dependencies. Keep the exact
  requirements and test commands, and keep the pinned Python version.
- Cache `uv`'s dependency downloads by the tracked requirements files
  and platform; **never** cache coverage results, test success, source
  validation or compiled binaries as proof of passing checks.
- Cache the pinned Gitleaks executable, not Gitleaks findings. Every PR
  revision still checks out full Git history and executes the scanner.
  Version changes invalidate that binary cache. A cache miss installs
  the pinned scanner using the pinned Go toolchain.
- Keep independent workflows concurrent and preserve PR-revision cancellation
  from PR #61, which does not cancel main, scheduled or manual runs.
- Do **not** use `pytest-xdist` blindly for Home Assistant/Recorder fixture
  suites: parallel isolation and equivalent coverage would need explicit
  validation first. Also do not delete duplicate safety gate checks merely to
  improve a benchmark.

## Verify and compare

After a PR CI run, compare all eight workflow conclusions, the same
coverage thresholds and the same security findings against baseline.
Use elapsed timestamps of the *individual jobs* rather than comparing a
queued-to-finished GitHub UI number (runner availability varies). Compare
both cold (initial dependency cache miss) and warm (next revision/main)
runs; caching benefits cannot be honestly quantified from a cold-only run.

Do not merge a faster run if any test was removed, coverage was weakened,
a security scan was skipped, or Windows-specific dependencies were not
installed and exercised.
