# Code signing policy

**Status: application preparation — NOT SignPath approved, NOT signed.** HAL Gaming
Control has no publicly trusted Windows executable release yet. This page
documents the proposed signing rules; it does not assert that the project has a
SignPath certificate or that Windows Smart App Control trusts the application.

## Project and source

- Product: **HAL Gaming Control** (part of HAL Systems)
- Source and maintenance: https://github.com/mhalak/hal-gaming-control
- License: [MIT](LICENSE)
- Windows download/status page: [Windows distribution](docs/windows_distribution.md)
- Privacy: [Privacy policy](PRIVACY.md)
- Vulnerability reporting: [Security policy](SECURITY.md)

The planned free OSS certificate provider is **SignPath Foundation**:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

This attribution describes the **intended provider only** until approval and a
successfully verified signed release. The publisher name in a successful
Authenticode certificate would be SignPath Foundation, not HAL Systems.

## Team roles and responsibility

- **Authors / maintainers:** GitHub repository collaborators with permission to
  maintain source and build workflows; project owner [@mhalak](https://github.com/mhalak).
- **Reviewers:** trusted maintainers reviewing externally contributed pull
  requests, including changes to the build, installation and release pipeline.
  No external contribution may be signed without a maintainer review.
- **Signing approver:** project owner [@mhalak](https://github.com/mhalak),
  acting as the human release approver. **Every release signing request requires
  explicit approval.** If more approvers are appointed, their memberships and
  roles must first be recorded and reviewed.
- **Submitter:** a dedicated, least-privilege CI identity within the approved
  SignPath signing policy, not a generic contributor or arbitrary local build.

All participants must enable MFA on both GitHub and SignPath. Actual MFA and
repository permissions must be verified by the owner before the application;
this file does not certify anyone's account settings. Approver and CI roles are
not yet provisioned in SignPath.

## What may be signed

Only HAL-owned Windows application binaries, built from reviewed public source
code in this repository:

- `SmartHouseGamingControl.exe` — Windows LocalSystem service and separately
  launched interactive-session helpers for foreground detection and popup UI
- `SmartHouseGamingUpdater.exe` — optional signed updater, installed separately
  and disabled by default

The installer and uninstall scripts remain readable PowerShell source. Bundled
third-party runtimes, DLLs, Python extension modules, and other upstream
binaries must **not** be signed with the HAL subscription unless SignPath
explicitly permits a particular owned derivative under its rules. Preserve
their existing publisher signatures. A ZIP / Ed25519 update manifest does not
replace Authenticode signatures on the owned executables.

All owned EXE version resources must identify **HAL Gaming Control** as product
name and have the matching Windows component version. The accepted SignPath
artifact configuration must enforce product/version and file-selection
restrictions; never sign arbitrary executables from a submitted ZIP.

## Source-to-release trust process

1. Review a pull request and merge to `main`; confirm current commit SHA,
   independent Windows version in `release.json`, and all required CI.
2. Build from a **clean, pinned** checkout on a GitHub-hosted Windows runner
   using our tracked `windows_agent/build.ps1`. Preserve the unsigned build
   as a short-lived GitHub Actions artifact with provenance, without
   installing or publishing it. **On public repositories, workflow artifacts\n   may be accessible to readers with suitable GitHub access; they must be\n   clearly marked UNSIGNED and never described as trusted downloads.**
3. Once SignPath has accepted this project, configure GitHub.com as a trusted
   build system, enable origin verification and a release-only signing policy,
   restrict to `main`, and require a human approval **for each request**.
   Verify the source revision and GitHub artifact ID using the official SignPath
   integration. Do not accept an uploaded local executable as a substitute.
4. Use SignPath's artifact configuration to sign **only** the two HAL-owned EXEs.
   Verify both final Authenticode signatures, certificate chain, matching
   publisher, timestamp, matching product/version resources, and signer
   thumbprint. A valid signature does not guarantee reputation or SAC approval.
5. Only **after signing**, package the signed files, install/uninstall scripts,
   version/build identity and SHA-256 checksums. The existing Ed25519 update
   manifest, if used, must sign hashes of the **final post-Authenticode ZIP**.
   The independent OTA trust key must be provisioned out of band.
6. Publish only after owner approval, independent Windows 11 Smart App Control
   and rollback acceptance, and immutable-version checks. Never move a signed
   version tag, overwrite artifacts, enable updater delivery, or skip review
   because CI is green.

**Distribution separation:** this repository's GitHub Releases are HA/HACS
version releases (`0.x.y`). Windows-only releases would confuse HACS version
selection. A dedicated, owner-approved Windows distribution repository or
separate channel is required before any public Windows ZIP is published. The
candidate build workflow intentionally has **no GitHub Release or signing
permissions**, and does not deploy to a PC.

## Security boundaries and end-user notice

Installing the Windows agent registers an **auto-start LocalSystem service**.
With an authorized Home Assistant MQTT automation it can lock the PC or
terminate one specifically verified foreground game; game progress can be lost.
The installer creates protected Program Files and ProgramData directories, and
optional OTA can add a protected scheduled task only with explicit operator
configuration. See [installation and rollback](docs/windows_deployment.md)
and [uninstallation](docs/windows_distribution.md#uninstalling).

The agent does **not** bypass Smart App Control, Defender, SmartScreen, UAC,
TLS verification or the user's Windows security choices. If Windows blocks a
package, stop and resolve signer/trust; never advise users to disable a security
feature. The deployment uses the user's own MQTT broker and HA instance:
see [privacy and network flows](PRIVACY.md).

## Present limitations and application blockers

- No accepted SignPath Foundation project, certificate, signing policy,
  signing API credentials or externally verified Authenticode build.
- The Foundation requires an **already released application in the form to be
  signed**. HA-only GitHub Releases and CI artifacts do *not* establish that
  requirement for a Windows executable. The owner must decide how to provide
  an appropriately labeled first Windows distribution for eligibility or ask
  the Foundation to assess the project before publication.
- The project's public reputation and signability are for the Foundation to
  decide. Repo settings, branch rules and MFA need owner verification.
- First real Windows 11 Smart App Control–enabled installation, update and
  rollback remain to be validated, including startup as LocalSystem and GUI
  popup behavior.

This policy follows https://signpath.org/terms and the official
[SignPath GitHub integration](https://docs.signpath.io/trusted-build-systems/github).
