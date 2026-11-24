## Agent 0.4.3 / HA 0.14.1 — SignPath release preparation (source only)

The Windows source build now embeds matching first-party **HAL Gaming Control**
ProductName and **0.4.3** ProductVersion/FileVersion PE resources in the
service and updater EXEs. The [Code signing policy](../CODE_SIGNING_POLICY.md)
and [Privacy policy](../PRIVACY.md) are public; the owner may run the
[unsigned candidate workflow](../.github/workflows/windows-signing-candidate.yml)
manually on `main` for internal review. It creates **no signed package,
GitHub Release or deployment**, and no signing credentials are used.

**SignPath has not accepted this project.** Existing HA GitHub Releases
are HA-only and Windows binary distribution remains separate, as described
on the [download/status page](windows_distribution.md). The former blanket
deployment HOLD #56 is closed; actual Windows safety/trust restrictions,
per-PC backups and supervised pilot still apply.

## Agent 0.4.2 / HA 0.14.1 — HAL branded gaming popup (source only)

The Windows service now has a strict, **non-retained** `SmartHouse/Gaming/<hostname>/ui/popup` UI v1 listener, separate from mandatory Unified MQTT v3 monitoring, and advertises `popup_ui_protocol: 1` only in this source version. A dedicated non-elevated `--popup-helper` in the active unlocked Windows user session displays a locally animated countdown, progress bar and up to three equal-width configured buttons. The process is accessed only via a protected SYSTEM-to-user named pipe. Child button IDs and close events go to HA via `ui/popup_event` and become `hal_gaming_control_popup_response` events for parent-authored automations.

**No real PC has been updated or verified.** PyInstaller packaging and LocalSystem→interactive desktop testing on Windows 10/11, including games in fullscreen and borderless, lock/logoff/session switches and MQTT outages, remain a separate acceptance gate. **#56 HOLD stays active**. This source change is not a signed release, installer, verified UI screenshot, or deployed update.

## Agent 0.4.1 / HA 0.13.13 — Uptime diagnostic presentation (source only)

Windows 0.4.1 changes only the **existing native MQTT Uptime discovery value template**: the unchanged Unified MQTT v3 numeric seconds appear as readable `Xd Yh Zm Ss` text in Home Assistant. The same native discovery unique ID, MQTT telemetry topic, availability and expiry are kept. HA 0.13.13 provides the same presentation in direct MQTT mode. Neither version installs itself or unlocks OTA; follow the approved deployment/security gate in [#56](https://github.com/mhalak/hal-gaming-control/issues/56).

**Compatibility note:** a Windows 0.4.0 agent continues sending valid v3 telemetry to HA 0.13.13, but its **native MQTT Uptime** remains numeric until its retained discovery config is refreshed by Windows 0.4.1. The Uptime state itself is now text; numeric automations should read the existing `system_uptime_seconds` attribute on **Active game** (or `uptime_seconds` on the HA-owned Direct MQTT Uptime).


## Agent 0.4.0 Preview 21 — 🚨 BREAKING: hostname-only device identity

**Current compatible Home Assistant:** 0.13.0+ consumes **Unified MQTT v3 only**. The Windows agent 0.4.0+ also publishes v3-only monitoring. There is no v2/scalar stream, HA protocol toggle or dual-publisher migration.

The **sole** MQTT `device_id` and retained discovery `name` come from the actual Windows computer name (for example `DESKTOP-F29J1R1`). The old YAML `device:` section is rejected. An old ProgramData `device_id` file is ignored and must not be copied to select an identity.

**One-PC supervised clean-cut upgrade:**

1. Record the old exact MQTT ID, current PC hostname, HA tracked apps, budgets, bonuses, automations and historical data. Make protected backups before changing anything.
2. Update restricted broker ACLs for the new exact hostname namespace. Verify the computer name is unique and valid.
3. Remove the obsolete `device:` block from the protected Windows `config.yaml`. Keep broker credentials and other supported settings.
4. Deploy reviewed Windows agent **0.4.0+** and verify `SmartHouse/Gaming/<hostname>/discovery` includes `unified_telemetry_protocol: 3`, availability is online, and fresh non-retained `.../state/telemetry` v3 packets arrive.
5. Upgrade HA to **0.13.0+**. No protocol option is presented: v3 is mandatory. A prior `unified_telemetry_enabled: false` is automatically discarded without changing other HA options or Recorder data.
6. Old HA entries still scoped to an old MQTT ID **cannot receive** the hostname stream. Explicitly add the new hostname-based PC, reconfigure per-device settings and test every sensor before enabling parent controls. Do not assume histories or entity IDs cross different device IDs automatically.
7. After verifying operation, remove exact obsolete project-owned discovery/availability entries only if authorized. Never delete the entire broker tree, unrelated entities or Recorder data.

**Rollback:** restore matched known-good HA and Windows backups. There is no telemetry v2 fallback or dual-source mode. Signed OTA distribution and real-device pilot remain separately gated by [#56](https://github.com/mhalak/hal-gaming-control/issues/56). The [Unified MQTT v3 guide](unified_mqtt_telemetry.md) is authoritative for the live protocol.

**Historical preview notes:** Older Windows 0.2.x transport/identity experiments and per-release details are kept in the [changelog](changelog.md) and [HA release history](ha_releases.md), not presented as supported installation paths.

Home Assistant (HA) and HACS run independently of the Windows companion. HACS installs only the HA integration; install one Windows service on each managed PC.

## Prerequisites

- Windows 10/11 x64; administrator access on the target PC.
- Running HA with MQTT and Recorder, and a reachable MQTT 5 broker.
- A unique restricted MQTT account per PC, scoped to the actual Windows hostname (the only supported `device_id`). Follow [MQTT setup](mqtt_setup.md).
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
