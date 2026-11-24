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
complete service/updater folder. Explicitly triggered candidate CI artifacts are **unsigned** and **not**\npublic software releases or verified Windows installers. They are short-lived\nGitHub Actions artifacts, potentially retrievable on the public repository;\nnever mistake them for trusted downloads. There is no promise that Smart App Control will allow a locally
built binary. Do not disable SAC, Defender or SmartScreen to work around a
blocked package.

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

## Public distribution readiness

The owner must still verify: SignPath OSS eligibility (**including the
Foundation's prior-public-release requirement**), GitHub MFA, code-signing
approver permissions, third-party bundled dependency licenses, file-version
resources, a SignPath origin-verified signing configuration, an independently
reviewed release channel, Smart App Control real-PC pilot and rollback.
A CI artifact is not a published Windows release and does not satisfy that
prior-release requirement automatically.
