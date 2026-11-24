# SignPath Foundation OSS application — preparation sheet

**Draft only. No application has been submitted, no signing credentials exist
in this repository and no Windows binary is signed.** The maintainer must
confirm all owner/account fields and send the application personally.

## Application facts (verified from this repository)

| Field | Value |
| --- | --- |
| Project | **HAL Gaming Control** |
| Maintainer / repository owner | [@mhalak](https://github.com/mhalak) |
| Public source | https://github.com/mhalak/hal-gaming-control |
| Project home | https://github.com/mhalak/hal-gaming-control#readme |
| License | [MIT](../LICENSE), for project-owned source |
| Code signing policy | https://github.com/mhalak/hal-gaming-control/blob/main/CODE_SIGNING_POLICY.md |
| Privacy policy | https://github.com/mhalak/hal-gaming-control/blob/main/PRIVACY.md |
| Windows download/status | https://github.com/mhalak/hal-gaming-control/blob/main/docs/windows_distribution.md |
| Target OS | Windows 10/11 x64 |
| Code to be signed | `SmartHouseGamingControl.exe` and `SmartHouseGamingUpdater.exe` (project-owned only) |
| Release target | First owner-approved Windows distribution in a **separate channel from HA/HACS** |

## Description for application form (verify before submitting)

> HAL Gaming Control is an MIT-licensed, self-hosted parental gaming-time
> monitoring and control project. Its Windows LocalSystem companion reports
> verified foreground game/app activity and display state to a parent-operated
> MQTT broker. Home Assistant manages daily/weekly budgets, bonus time and
> explicitly authorized lock/terminate actions. The companion also displays
> optional user-session countdown notifications. There is no HAL-operated
> gaming telemetry cloud or mandatory online account. The Windows agent and
> optional updater are written and maintained from the public source
> repository. We seek SignPath Foundation OSS Authenticode signing for the
> project's own two Windows executables so family administrators can install
> a verifiable release without disabling Windows protections. Signing will
> be from GitHub-hosted CI with source origin verification and a manually
> approved release request.

**Do not claim** that unsigned builds already have a trusted publisher or that
Windows Smart App Control is guaranteed to accept signed executables.

## Build the reviewed unsigned Windows candidate

The source-only preparation does not prove that PyInstaller produced a usable
Windows package. A deliberate owner-triggered CI run can produce the first
Windows **build candidate**, without using SignPath or publishing a Release.

After all eight CI gates pass for current `main`, the repository owner can
either manually launch the
[Windows unsigned candidate workflow](../.github/workflows/windows-signing-candidate.yml)
with GitHub Actions `workflow_dispatch`, or post exactly this comment **on
issue #9**, with the declared Windows version substituted:

```text
/build-windows-candidate 0.4.3
```

The workflow accepts the command only when posted by GitHub user `mhalak`,
on issue #9, using current `main` and an **exact match** to the version
currently in `release.json`. Any stale or misspelled command fails before
building. Outputs are short-lived **UNSIGNED** GitHub Actions artifacts,
not publicly trusted packages, GitHub Releases or proof of SignPath
eligibility. The workflow never installs onto a PC or enables updater OTA.

Inspect the run logs and archive for clean source SHA, Python tests, both
owned EXEs, exact PE product/version fields, SHA-256 hashes, installed
`version.txt`, matching `build-info.json`, and an expected
`NotSigned` Authenticode status. Preserve a sanitized result in issue #9.
No release to users or SAC workaround is authorized by this build alone.

## Owner actions before submitting

- [ ] Confirm GitHub repository visibility, code ownership, MIT licensing of
      all project-owned components and redistribution rights for bundled
      dependencies and artwork.
- [ ] Confirm every maintainer/signing approver has MFA on GitHub; enable MFA
      on SignPath once invited. Do not put MFA recovery codes or API tokens in
      issues or commits.
- [ ] Verify owner is prepared to serve as manual signing approver for every
      release, with reviewed code and build workflow changes.
- [ ] Resolve the Foundation's requirement for an **already released Windows
      application in the intended form**. Existing HA-only Releases and
      source CI artifacts are not sufficient. Obtain the Foundation's guidance
      on a carefully labeled unsigned Windows pre-release if necessary;
      do not present one as trusted or publish automatically.
- [ ] Confirm actual public Windows download URL and first package scope.
      SignPath independently evaluates project reputation and eligibility.
- [ ] Submit at https://signpath.org/apply.html using the maintainer's own
      identity and email; no email or personal identity is invented here.
- [ ] On acceptance: configure SignPath Foundation organization/project,
      trusted GitHub.com build system + GitHub App, origin verification,
      release-signing-only policy, manual approval, and an artifact
      configuration signing precisely the two owned EXEs with enforced
      product/version metadata.
- [ ] Add narrow protected GitHub credentials/configuration **after approval**
      and security review, not in a PR. Require SHA-pinned dependencies and
      transparent source/build provenance; compare final signed output with
      GitHub's approved build artifact.
- [ ] Verify both SignPath Authenticode signatures, certificate chain,
      timestamps and file versions; generate release archive/Ed25519 manifest
      **after** signing, in a separate Windows distribution channel.
- [ ] Run a supervised Windows 11 Smart App Control ON / Defender ON pilot
      with install, start, popup, command safety, update, rollback and
      uninstall before recommending public use.

## Important division of responsibility

This repository can prepare the files and CI tests. Only the owner can provide
their legal/contact information, enable MFA, approve a SignPath application,
select the public distribution channel, and approve a real signing request.
**CI must never simulate or automatically infer those approvals.**

SignPath sources:
- https://signpath.org/terms
- https://signpath.org/apply.html
- https://docs.signpath.io/trusted-build-systems/github
- https://docs.signpath.io/projects
