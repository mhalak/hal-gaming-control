# Windows deployment guide

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
- A unique device ID, name and restricted MQTT account per PC; follow [MQTT setup](mqtt_setup.md).
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

Set the unique device ID, name, MQTT host/port and credentials. The following is a TLS example; the broker needs TLS enabled on its configured port. Adjust rules for actual game installations.

```yaml
device:
  id: gaming_pc_01
  name: Gaming PC 1
mqtt:
  host: BROKER_HOST
  port: 8883
  username: gaming_pc_01
  password: REPLACE_WITH_SECRET
  tls: true
  # ca_certs: absolute path to a trusted CA file, if required
  discovery_prefix: homeassistant
gaming:
  check_interval_seconds: 1
games:
  - name: Roblox
    process: RobloxPlayerBeta.exe
  - name: Minecraft Java
    process: javaw.exe
    command_line_arg: net.minecraft.client.main.Main
  - name: Minecraft Bedrock
    process: Minecraft.Windows.exe
update:
  enabled: false
```

Use a CA trusted by the service; do not turn off certificate verification. Generic runtimes such as Java need an additional exact argument or executable path constraint. Never put actual passwords in Git, diagnostics or screenshots.

Open an elevated PowerShell inside the staging directory:

```powershell
.\install.ps1 -Config .\config.yaml
Get-Service SmartHouseGamingControl
Get-CimInstance Win32_Service -Filter "Name='SmartHouseGamingControl'" |
  Select-Object Name, State, StartMode, StartName, PathName
Get-Content "$env:ProgramFiles\SmartHouseGamingControl\version.txt"
```

Expected: Running, Automatic, LocalSystem. The installer places binaries in Program Files and config/logs in protected ProgramData. It deliberately refuses an already installed service. Remove temporary copies of config.yaml after verifying the protected installed copy.

## Pair and validate

1. Confirm the HA MQTT connection and running Windows service.
2. In HA MQTT's topic listener, observe the exact device root SmartHouse/Gaming/gaming_pc_01/discovery, availability, state/uptime, state/in_game and state/current_game. Uptime advances roughly every 60 seconds; availability must transition online after a fresh snapshot. Metadata includes agent_version.
3. Install the HA integration (manually, or via HACS when validated). Restart HA, go to Settings → Devices & services → Add integration and select HAL Gaming Control and the advertised PC.
4. Verify raw telemetry, budget controls and Windows agent version on the device. Keep Current game and Uptime in Recorder with at least eight days' retention.
5. Launch and close a disposable game. Current preview behavior reports matching running processes, even in the background; do not confuse that with actual foreground play.
6. Test explicit Terminate game / Lock PC only in authorized disposable sessions. Termination may lose progress; lock is not a permanent lockout. Do not send commands just to test connectivity.
7. Reboot the PC when authorized and verify automatic service startup, fresh telemetry and the reported version. Repeat for other PCs with unique IDs and credentials. See [acceptance checklist](acceptance.md).

## Edit configuration

Edit the protected installed config as an administrator:

`$env:ProgramData\SmartHouseGamingControl\config.yaml`

Keep its device ID and ACL unchanged. Restart the service after authorized edits. Do not change HA's shared broker or another PC's credentials merely to change one PC.

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
