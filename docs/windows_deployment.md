## Agent 0.4.0 Preview 21 — 🚨 BREAKING: hostname-only device identity

**Not a transparent upgrade.** From Windows **0.4.0**, both the MQTT routing ID and discovery `name` are the current Windows computer name, for example `DESKTOP-F29J1R1`. The agent no longer uses or creates a random/persisted `device_id`; neither `device.id` nor `device.name` can override the OS name. **An existing `device:` section in `config.yaml` is rejected at startup.** The existing ProgramData `device_id` file is ignored (not deleted automatically, so rollback remains possible).

**Before installing on each PC (one-PC pilot first):**

1. Confirm the Windows OS name using `$env:COMPUTERNAME` and record the **old** exact MQTT prefix (e.g. `SmartHouse/Gaming/desktop_lucija`), HA device/config entry, tracked applications, budgets, bonus state, automations and Recorder history. Make a HA backup and a protected ProgramData backup. **Renaming the Windows PC later is another breaking identity migration.**
2. Verify HA **0.12.0+** and its Unified MQTT v3 support. Prepare broker ACLs permitting that PC's MQTT account to publish/subscribe under the **new, hostname-based** prefix. Ensure hostnames are unique; if this is not possible, do not deploy. Do not disable broker access control to work around an ACL mismatch.
3. From the protected `%ProgramData%\SmartHouseGamingControl\config.yaml`, **remove the entire legacy `device:` block**. Keep only the broker details and other supported options. The old `device_id` file may be kept for rollback but **has no effect** on 0.4.0. Do not copy/delete it as a way to rename the device.
4. Install the **reviewed** Windows 0.4.0 build using the normal supervised deployment method. Expect discovery under `SmartHouse/Gaming/<WINDOWS_COMPUTERNAME>/discovery` and v3 observations under `.../state/telemetry`, with matching `device_id` and `name` values. Check live MQTT traffic, no unauthorized cross-device messages and the actual reported agent version.
5. Home Assistant sees a **new device identity**, not an update to the old one. Enroll it, enable the v3 telemetry source **for the new HA config entry**, and restore/review the necessary app mappings, quotas, schedules, controls and automations before any enforcement. Test verified live foreground, Uptime and availability. The new device's Recorder history is **not** automatically joined to the old device's history.
6. Only after verifying the replacement, remove the **old HA entry** and, if needed, clear **exact old project-owned retained discovery/availability/config topics** on the broker with authorized tools. Do not delete broad `SmartHouse/Gaming/#` trees, unrelated MQTT discovery or Recorder data. If cleanup fails, keep the old retained topics documented and do not enable enforcement on stale entities. Retain the backed-up identity file until rollback is no longer needed.

**Rollback:** restore the previous Windows binary/config, old device-scoped broker ACLs and compatible HA config/source selection together. Never rely on the new hostname namespace to receive an old-device update command. Signed OTA and on-device acceptance remain separately gated; this changelog does **not** mean deployment was completed.

## Windows agent 0.2.12 Preview 18 — stable updater status identity (#166 follow-up)

Fixes the separate Windows SYSTEM updater's MQTT status client for the default minimal Windows configuration: the auto-generated per-installation `device_id` is persisted in protected ProgramData, while `config.yaml` contains no `device.id`. Update progress now uses the persisted ID and stays device-scoped, rejects symlinks, malformed IDs and conflicting YAML/persisted identities, and preserves legacy YAML-only installations. Adds regressions for all four paths. Screen Idle bonus support (#92) in HA 0.11.0 is also opt-in and still needs a physical Windows acceptance test. Signed OTA activation remains default OFF and the [integrated deployment gate](https://github.com/mhalak/hal-gaming-control/issues/56) remains HOLD pending authentic signed artifacts, bootstrap, backups and one-PC Smart App Control acceptance.

## Windows agent 0.2.11 Preview 17 — signed MQTT OTA Install handoff (#166)

This is **source code readiness**, not proof of a safe production installation. The optional v2 receiver requires all of `update.enabled`, `update.mqtt_staging_enabled`, and `update.mqtt_install_enabled` to be explicitly true plus a protected ProgramData `updater.json` with `mqtt_install_enabled: true`, a locally pinned Ed25519 PUBLIC key and a preapproved Authenticode signer thumbprint. The directory `ota-staging` must exist and be protected. Without this supervised bootstrap the receiver remains v1 stage-only or disabled and the HA Install button must not start MQTT installs. Never disable Smart App Control/Defender or rerun the fresh-service installer over an existing installation.

For the exact wire format, two-part Windows signature verification, safe transactional update and one-PC acceptance criteria, see [Signed MQTT OTA v2](mqtt_ota.md#signed-mqtt-ota-v2--preview-17-source-candidate-166). No signed Windows release binary or production signing key is bundled in this repository, and the live TrueNAS deployment remains on HOLD.

## Windows 0.2.10 Preview 15 — optional stage-only MQTT OTA receiver (#166)

**Developer-only, deliberately disabled.** Adds an explicit `update.mqtt_staging_enabled: true` mode requiring `update.enabled: true` and a pre-existing protected ProgramData `ota-staging` directory. In this mode the agent receives bounded, device-scoped MQTT 5 packages and publishes non-retained ACKs, but **never installs, unpacks, runs or passes a staged file to the Windows updater**. Staged ZIP content is untrusted. Normal installations do not subscribe to OTA topics, and cannot enable them through HA. The source-only HA sender exists, but no runtime HA OTA sender/Install flow is connected. Do not enable on family PCs; use an isolated, signed-build-capable development VM. See [MQTT OTA protocol](mqtt_ota.md). HACS integration stays at **0.8.0**; a Windows-only version bump does not require an HA release.

# Windows deployment guide

## Windows 0.2.9 Preview 8 — safe HA-targeted manual termination (#155)

A **new PC still needs only MQTT broker details** in its Windows config; its ID and name are automatic. Together with **HA 0.7.2**, it offers an HA-owned **Terminate active game** button without a Windows `games` catalog. The button is available only when the selected PC has a recently verified **tracked foreground app** and an expiring agent-issued one-use token for that exact observation. Windows reads a fresh interactive-user foreground sample after the command, checks private PID/process start/session/signature and system-process protections, and terminates **one** verified process. A change of window or session, stale state, generic unidentifiable Java, missing sample, replay or reconnection causes a safe refusal. This is *manual* only; gaming restrictions never automatically kill apps.

Existing PCs with a legacy `games` block keep the original native MQTT **Terminate game** button and its previously limited allowlist-based behaviour. No targeted offer is issued in that mode. You may keep that block through upgrade. Only a deliberate move to a rule-free config enables the new HA-controlled targeted button; the old native button is then withdrawn and a stale direct-mode legacy button remains unavailable. No registry purge, recorder reset or new device ID is required.

**Pilot checklist before deployment:** back up the protected ProgramData config and `device_id` file, keep automatic enforcement disabled, upgrade HA first, then agent on one PC. Confirm raw foreground identity and HA Tracked applications are correct; verify the new control is unavailable when idle/offline/untracked or when another window is focused. Use a disposable game session for an explicitly authorized manual terminate, and check that *only that exact process* stops. Verify lock still works, reboot/reconnect, and use the complete binary rollback if a service/session/security check fails. The CI pipeline cannot substitute for the physical LocalSystem-to-interactive-session test.

See [targeted MQTT protocol](mqtt_protocol.md) and [acceptance checklist](acceptance.md). **No physical pilot or public signed installer is claimed.**

## Windows 0.2.8 Preview 7 — MQTT-only setup, safe manual-control compatibility (#155)

A **new Windows installation no longer needs a local `games` catalog**. Configure only `mqtt.host`, `mqtt.username` and `mqtt.password` (and TLS/port when needed). Agent ID remains stable in protected `device_id`; its advertised name comes from Windows. App enrollment/naming, budgets and limits remain in Home Assistant; raw v2 foreground telemetry works without Windows rules.

**Manual controls:** `Lock PC` remains available. The legacy `Terminate game` button requires a non-empty local `games` allowlist: without rules the agent *does not subscribe* to that command, does not advertise it as a capability, and publishes an exact retained tombstone only for its own previous native MQTT terminate button. An existing HA direct/scoped button created before migration is marked unavailable after the agent's live discovery metadata revokes the capability. No arbitrary process termination, automatic enforcement or updater is introduced. For existing PCs, keep the old `games` block unchanged to preserve manual termination until an HA-authoritative safe command is implemented in a separate reviewed step of #155.

**No surprise migration:** Removing `games` is optional. Neither a service upgrade nor HA update deletes the legacy configuration, tracked-app mapping, stable device ID, budgets or history. If deliberately switching an existing PC to rules-free mode, back up its config first and restart the service; confirm `Lock PC`, uptime and foreground tracking, and check that `Terminate game` is unavailable. On rollback restore the previous binaries and prior `games` config. One-PC physical acceptance remains required; do not enable automatic enforcement.

Minimal local config:

```yaml
mqtt:
  host: BROKER_HOST
  username: THIS_PC_MQTT_ACCOUNT
  password: REPLACE_WITH_SECRET
```

## Windows 0.2.7 Preview 6 — automatic PC identity (issue #155, first safe increment)

The Windows agent now derives its discovery name from the **current Windows computer name**. Do not type or maintain `device.name`. On a fresh installation without `device.id`, it generates a random, stable per-install ID and saves it as `%ProgramData%\\SmartHouseGamingControl\\device_id` in the same administrator/SYSTEM-protected directory as `config.yaml`. It reuses this ID after service restart, PC renaming, or binary update. Keep this file with the ProgramData directory across reinstalls, because a lost ID creates a new HA device and MQTT topic root. Do not copy the identity file between PCs.

**Upgrade:** if the installed `config.yaml` still specifies `device.id`, the existing ID is kept and written to `device_id` the first time this version starts. You may then remove the entire legacy `device` section; the identity stays the same. If a stored ID and explicit configured ID disagree, the service deliberately fails to start rather than silently creating a second identity. Back up both before making manual changes. The old `device.name` value is ignored; rename the device in Home Assistant to your preferred visible label. User-defined HA device names take precedence over the default discovered name.

**Not yet zero-config:** the legacy `games` list is still required for safe manual `Terminate game` support. Foreground app enrollment and display names are configured in HA, but we must migrate the termination command before removing Windows rules. This is tracked in #155. No forced shutdown and no remote updater are enabled by this change.

## Windows 0.2.6 Preview 5 — retire native agent-derived activity discovery

This source prepares the native MQTT discovery side of issue #67: new Windows agents
stop advertising the legacy `Current game`, `In game`, `Gaming active`, and
agent-derived `Active game` entities. On a verified full discovery resync,
their **exact agent-owned retained discovery config topics** receive empty
tombstone payloads. The agent still advertises Uptime, Lock PC and Terminate
game, and it still sends raw v2 foreground identity data to the HA-owned
`Active game` entity. Legacy wire telemetry and local rule handling may
temporarily remain for rollback and manual termination; neither is used by
the HA foreground budget accounting.

**Clean-start dependency (owner-approved):** use reviewed HA 0.5.4
and Windows 0.2.6, and follow `docs/foreground_migration.md`. Old gaming
Recorder history and original native `Active game` entity ID **do not need
preservation**. Capture the exact old PC entity IDs before deletion and
purge only their history with HA's `recorder.purge_entities`, never the
shared HA database. The HA-owned new Active game may receive a new entity
ID; prevent duplicates by verifying native tombstones and scoped cleanup.
Keep the one-PC TrueNAS pilot and safe rollback gates. No automatic
enforcement or remote updater activation.


## Windows 0.2.5 Preview 4 — additive HA-owned foreground identity transport

A new **non-retained, expiring MQTT v2** message on `SmartHouse/Gaming/<device_id>/state/foreground_identity` carries `{version:2, device_id, epoch, sequence, observed_at, state, process, signature}`. `state` is `foreground`, `idle`, or `unknown`. A verified foreground application sends only a safe executable basename and optional vetted Java main-class/JAR/module signature; PID, process path, full argv, credentials, window title and user names remain local. This stream does **not** consult the Windows `games` rules.

This update is **transport preparation**, not a completed HA cutover. The legacy `foreground_snapshot`, legacy rules and explicit manual commands coexist temporarily for compatibility. HA source normalization, durable accounting, old entity cleanup and the one-time re-enrollment of applications in HA still require reviewed follow-up work (#4/#7); do not deploy v2 alone as a completed feature. The HA config-entry `options.tracked_apps` persists aliases across upgrades and is not sent to Windows. Preserve OS protections, verify the exact source/build SHA, roll out one approved gaming PC at a time and keep restrictions disabled until validated (#56).


Home Assistant (HA) and HACS run independently of the Windows companion. HACS installs only the HA integration; install one Windows service on each managed PC.

## Prerequisites

- Windows 10/11 x64; administrator access on the target PC.
- Running HA with MQTT and Recorder, and a reachable MQTT 5 broker.
- A unique restricted MQTT account per PC; the Windows name and stable device ID are generated/resolved automatically (see above). Follow [MQTT setup](mqtt_setup.md).
- A trusted Windows build machine with Python 3.12 x64 when building from source.
- Disable automatic restrictions during installation, upgrade and testing. Close valuable game sessions.

## Build and stage

For this source preview, build from a reviewed revision. A production installation should use a reviewed compatible release. Clone on the trusted build machine:

```powershell
git clone https://github.com/mhalak/hal-gaming-control.git
Set-Location hal-gaming-control
git checkout --detach REVIEWED_COMMIT_SHA
git rev-parse HEAD
Set-Location windows_agent
.\build.ps1
```

The script creates a virtual environment, installs dependencies, runs tests and creates the agent and updater PyInstaller onedir builds. Check build success and `dist/SmartHouseGamingControl/version.txt` and `build-info.json`. The central root `release.json` supplies the version; an optional `-Version` argument must match it. A clean Git checkout is required, with the same identity before and after a successful build. Use a fresh trusted checkout without local ignored source overrides, verify the intended commit and record the package hash separately. Never deploy output of a failed build or relabel older code. See [release identity](release_identity.md).

Copy the complete dist/SmartHouseGamingControl directory, install.ps1, uninstall.ps1 and config.example.yaml to a trusted local staging directory on the target PC, retaining the same layout. The target PC needs neither Python nor Git credentials. Never copy only the executable. The optional updater additionally requires dist/SmartHouseGamingUpdater.

A future verified binary distribution can provide windows-install-X.Y.Z.zip, its signed manifest and detached signature. The archive authentication and Windows Authenticode trust are distinct; neither removes the need for ordinary Windows security checks. No public installer is currently advertised. Never disable Smart App Control, Defender or other security policies to run an untrusted binary.

### Known Smart App Control incompatibility

Unsigned development builds have been blocked by Windows 11 Smart App Control (service start error 4551 / event 7000). Administrator elevation does not override this policy. If blocked, stop deployment and retain or restore the last working trusted installation. See [known limitations](known_limitations.md) for observed evidence and the permanent signing requirement. Public distribution requires trusted Authenticode-signed binaries validated with SAC enforced; an Ed25519 release manifest alone is insufficient. Do not disable Windows security to install an untrusted binary.

## First install

Create a private configuration in the staging directory:

```powershell
Copy-Item .\config.example.yaml .\config.yaml
notepad .\config.yaml
```

Set the MQTT connection fields. No device ID, display name or local app rules are needed on new PCs. The following example uses optional TLS; the broker must have TLS enabled on the given port. Legacy termination rules are still accepted when upgrading an old PC.

```yaml
mqtt:
  host: BROKER_HOST
  port: 8883
  username: THIS_PC_MQTT_ACCOUNT
  password: REPLACE_WITH_SECRET
  tls: true
  # ca_certs: absolute path to a trusted CA file, if required
```

Use a CA trusted by the service; do not turn off certificate verification. For legacy optional `games` rules, generic runtimes such as Java still require an additional exact argument or executable path constraint. Never put actual passwords in Git, diagnostics or screenshots.

Open an elevated PowerShell inside the staging directory:

```powershell
.\install.ps1 -Config .\config.yaml
Get-Service SmartHouseGamingControl
Get-CimInstance Win32_Service -Filter "Name='SmartHouseGamingControl'" |
  Select-Object Name, State, StartMode, StartName, PathName
Get-Content "$env:ProgramFiles\SmartHouseGamingControl\version.txt"
$env:COMPUTERNAME  # Windows 0.4.0+ uses this as both MQTT identity and discovery name
```

Expected: Running, Automatic, LocalSystem. The installer places binaries in Program Files and config/logs in protected ProgramData. It deliberately refuses an already installed service. Remove temporary copies of config.yaml after verifying the protected installed copy.

## Pair and validate

1. Confirm the HA MQTT connection and running Windows service.
2. With Windows agent **0.4.0+**, inspect `SmartHouse/Gaming/<WINDOWS_COMPUTERNAME>/discovery` and `.../state/telemetry` (v3, non-retained) plus `.../availability` (retained). The discovery `device_id` and `name` must both match `$env:COMPUTERNAME`, with `agent_version: 0.4.0`. Native MQTT Uptime is derived from `system.uptime_seconds` in v3. Do **not** rely on a saved `device_id` file or the retired v1/v2 scalar monitoring topics.
3. Install the HA integration (manually, or via HACS when validated). Restart HA, go to Settings → Devices & services → Add integration and select HAL Gaming Control and the advertised PC.
4. Verify current raw foreground telemetry, HA-owned Active game, budget controls and Windows agent version on the device. The retired process-presence `Current game` entity is not required for HA 0.7.x foreground accounting. Preserve existing HA history and the HA-owned foreground ledger; do not purge Recorder as part of this update.
5. Launch and close a disposable game. On Windows **0.4.0+**, verify that the v3 **foreground** sample and HA accounting reflect only verified focused play; do not infer gameplay from a background legacy process-presence topic.
6. On new rule-free installs, confirm that `Lock PC` is available and `Terminate game` is not advertised or cannot be pressed. Only test legacy `Terminate game` on PCs intentionally retaining local `games` rules, in an authorized disposable session. Termination may lose progress; lock is not a permanent lockout. Do not send commands just to test connectivity.
7. Reboot the PC when authorized and verify automatic service startup, fresh telemetry and the reported version. Repeat for other PCs with unique IDs and credentials. See [acceptance checklist](acceptance.md).

## Edit configuration

Edit the protected installed config as an administrator:

`$env:ProgramData\SmartHouseGamingControl\config.yaml`

For Windows **0.4.0+**, the entire YAML `device:` section must be **absent**; the computer name is read from Windows and cannot be overridden in the agent. The obsolete ProgramData `device_id` file is ignored but may be retained only as rollback evidence. Restart the service after authorized edits. Do not change HA's shared broker or another PC's credentials merely to change one PC.

## Manual upgrade and rollback

Build and test on a trusted machine before touching the running service. Check installed version and recorded source revision; skip if already current. Do not run the fresh installer over an existing service.

1. Record service account, startup/recovery settings, executable path and installed version. Disable restrictions; ensure no scheduled updater transaction is active.
2. Stage the entire trusted replacement onedir tree and verify its version. Keep an admin-only complete backup of the existing binary tree and protect any backups containing configuration or logs. Preserve ProgramData and service registration.
3. Stop the service and wait for Stopped. Move the old binary directory to a protected same-volume backup, then copy the complete staged directory to the original Program Files path. Preserve restrictive permissions and verify the executable path. Do not overwrite individual files in a running service.
4. Start the original service. Confirm fresh online MQTT state, advancing uptime, expected HA version diagnostic, and a non-destructive telemetry test. Do not restore enforcement until healthy.
5. If validation fails, stop the replacement, retain sanitized diagnostics privately, move failed binaries aside, restore the entire previous directory and restart. Verify the old version and telemetry. If rollback fails, leave restrictions disabled and resolve as administrator; preserve recovery evidence.
6. Record old/new versions, SHA, tests and rollback location. Roll out to the next PC only after validation.

For the experimental optional updater design see [remote update design](remote_update.md) and [HA update settings](ha_remote_update.md). There is no trusted public binary or signed update channel for this preview; keep automatic updates disabled.

## Stop or uninstall

From elevated PowerShell:

```powershell
Stop-Service SmartHouseGamingControl
.\uninstall.ps1
```

Uninstall unregisters the service and optional scheduled task; program files and protected data/logs remain. Disable dependent HA automations and remove the HA device config entry if no longer needed. Delete only verified application-owned files and this device's retained MQTT metadata when intentionally disposing of the installation. Revoke its broker credentials. Never clear other devices' topic trees.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Service will not start | Installer output, Event Viewer, local service.log, configuration syntax. |
| Access denied / blocked executable (including error 4551) | File ACLs, Code Integrity / Smart App Control events, package trust and Authenticode signature status. Stop deployment if blocked; see [known limitations](known_limitations.md). |
| No connection | DNS, firewall, broker host/port, MQTT 5, account ACL and CA. |
| No PC found in HA | Exact discovery topic, matching device ID, valid metadata; use scoped onboarding if global discovery is off. |
| Offline or stale | Service and broker connectivity; wait for fresh state and uptime. Last reported version is not proof of liveness. |
| Minimized games use budget | Known preview process-presence accounting, not focus accounting. |
| Update unavailable | Optional mirror, keys and catalog not provisioned; manual deployment still works. |

The rotating service log is at `$env:ProgramData\SmartHouseGamingControl\service.log`. Keep configuration and logs private; redact all real names, paths, addresses, credentials and command lines before sharing diagnostics.
