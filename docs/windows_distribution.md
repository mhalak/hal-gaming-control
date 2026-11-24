# Windows companion — downloads and distribution

**Status: DEVELOPMENT PREVIEW / SOURCE ONLY.** The Windows **0.4.3**
companion exists in source code, but there is currently **no approved
publicly trusted or SignPath-signed installer**. Do not treat the HA
[GitHub Releases](https://github.com/mhalak/hal-gaming-control/releases)
as Windows binary releases. The HA integration is distributed separately.

## What this software does

HAL Gaming Control is a self-hosted Windows gaming monitor and companion for
Home Assistant. With a local administrator-provided MQTT connection it
reports the current tracked foreground app and screen state, allowing HA
to calculate gaming-time budgets. HA can send explicit, authorized PC-lock
and verified active-game termination commands. An interactive Windows
popup can show remaining-time warnings and return response button IDs to HA.
There is **no default autonomous enforcement** on the PC.

The Windows component runs as **LocalSystem** at startup; the foreground
and popup helpers run in the active Windows user session. Parent commands
can lock the desktop or close a game, including unsaved work. Install
only on PCs you administer, after informing people using them.

## Current access

- **Source:** https://github.com/mhalak/hal-gaming-control
- **Windows build guide:** [Build and stage](windows_deployment.md#build-and-stage)
- **Version declarations:** [Release identity](release_identity.md)
- **Security:** [SECURITY.md](../SECURITY.md)
- **Privacy policy:** [PRIVACY.md](../PRIVACY.md)
- **Code signing policy:** [CODE_SIGNING_POLICY.md](../CODE_SIGNING_POLICY.md)

The Windows source build runs tests and uses PyInstaller to assemble a
complete service/updater folder. Explicitly triggered candidate CI artifacts are **unsigned** and **not**
public software releases or verified Windows installers. They are short-lived\nGitHub Actions artifacts, potentially retrievable on the public repository;\nnever mistake them for trusted downloads. There is no promise that Smart App Control will allow a locally
built binary. Do not disable SAC, Defender or SmartScreen to work around a
blocked package.

## Windows release channel in this same repository

**Prepared, NOT activated (issue #9):** An owner-only manual GitHub Actions
workflow at [Publish Windows unsigned preview to Pages](../.github/workflows/windows-public-preview-pages.yml)
can build a versioned Windows ZIP and stage its public download page. It is
deliberately separate from **GitHub Releases**, which belong to the HA
Marketplace. We will **not** create a second repository.

The intended Windows download location, **only after the owner explicitly
publishes a package**, is:
`https://mhalak.github.io/hal-gaming-control/windows/0.4.3/`

Do **not** assume this URL currently hosts a package. The owner must first
configure **Settings → Pages → Build and deployment → Source: GitHub Actions**
in the existing repository, review relevant GitHub Pages access/limits, and
approve public distribution of an explicitly **UNSIGNED** candidate.
The workflow is never started by a PR, merge, push, or an issue comment.
Only `mhalak` may manually launch it from `main`, providing exact
`release.json` Windows version and source SHA plus the
`PUBLISH_UNSIGNED_WINDOWS_PREVIEW` choice (default is `DO_NOT_PUBLISH`).
The Windows Preview build uses `preview-constraints.txt` to constrain
audited package versions and `preview-license-snapshot.json` to verify the
actual installed CPython/wheel identities. `tools/windows_preview_licenses.py`
stages the source environment's available license texts and hashes.
`tools/windows_download_page.py` refuses to package the ZIP unless
`LICENSE`, `THIRD_PARTY_NOTICES.md` and matching staged upstream license
files are present. These are **technical checks only**: the
[third-party inventory](../THIRD_PARTY_NOTICES.md) still lists unresolved
redistribution terms and missing upstream notices. A complete third-party
license/notice review, including Microsoft runtimes, and reproducible
hash-locked dependencies are required **before any public publication**.

The two project-owned EXEs must report `NotSigned`, pass version checks,
and have green 8/8 main CI before packaging. A ZIP, SHA256SUMS and source
manifest are published as static Pages files; no tag or GitHub Release is
created. The workflow verifies that the latest HA GitHub Release still
matches the HA manifest and version. No signing request or OTA is issued.

GitHub Pages is intended for a **small public archival source preview**, not
a long-term CDN for multiple large binaries. Monitor site size, download
availability and any Pages use limitations. A subsequent signed release
may require an independently reviewed scalable distribution method that
still uses this same source repository.

**Important:** even when published, this preview would be **UNSIGNED** and
not trusted by Windows. Never disable Smart App Control, Defender or
SmartScreen to run it. Do not install it onto family PCs merely to satisfy
SignPath's requirement for an already released application.

## Planned verified public download

Once the project is accepted by the SignPath Foundation, the maintainer will
announce a **separate** Windows download location and exact package/version,
with a SHA-256 digest, provenance and verified Authenticode signatures. The
download page will link this signing policy and privacy policy.

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

**This is a planned attribution, not a claim that the current preview is
signed.** An eligible Windows public package must be the final archive of
already signed, publisher-verified files; the signed updater archive/manifest
must cover those same final bytes.

## Installing

Use the [Windows deployment guide](windows_deployment.md) for the current
source-based development procedure. A trusted adult administrator must
configure the MQTT broker address and authentication, select tracked
applications in HA, and explicitly run the install process with elevated
permission. Installation creates a persistent service and protected program
data. Optional remote updates are OFF until separately provisioned.

**Privacy notice:** the agent transmits PC identity, tracked application
activity, gaming/display state and command status to the configured MQTT
broker and the owner's HA system. A remotely configured broker receives
these data remotely; TLS is optional but recommended for non-local transport.
Read the full [privacy policy](../PRIVACY.md) before installing.

## Uninstalling

From an elevated PowerShell with a trusted checkout of the same project,
run `windows_agent/uninstall.ps1` as documented in the
[Windows deployment instructions](windows_deployment.md#stop-or-uninstall).
It removes the service registration and optional updater task, but **keeps**
protected program data, config and logs for rollback. The administrator can
separately review any retained project-owned files and clear the specific
HA/device data after making backups. Do not remove unrelated broker entries.

## Third-party licenses and notices

**Status: inventory complete / items NOT CONFIRMED.** The technical inventory
of third-party components in the Windows package (Python runtime, PyInstaller
bootloader and its exception, `cryptography`, `paho-mqtt`, `psutil`, PyYAML,
`pywin32`, bundled DLLs, Tcl/Tk) and the artwork/resource provenance record is
in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). It is an engineering
inventory, not a legal opinion. Open items include Microsoft runtime
redistribution terms, the `pywin32` metadata/license mismatch and per-crate
notices inside `cryptography`. The package does **not** yet ship these notices
and the build has no dependency lock file; both are separate owner decisions
tracked in issue #9. Do not publish the unsigned preview until they are
decided.

## Public distribution readiness

The owner must still verify: SignPath OSS eligibility (**including the
Foundation's prior-public-release requirement**), GitHub MFA, code-signing
approver permissions, third-party bundled dependency licenses, file-version
resources, a SignPath origin-verified signing configuration, an independently
reviewed release channel, Smart App Control real-PC pilot and rollback.
A CI artifact is not a published Windows release and does not satisfy that
prior-release requirement automatically.
