# HAL Gaming Control — Windows MQTT agent

For an end-user installation, manual upgrade, rollback and troubleshooting, follow the [Windows deployment guide](../docs/windows_deployment.md). This document describes the underlying service and protocol. The foreground-enabled build is an unvalidated development candidate; do not deploy it as a stable release.

The Windows service reports telemetry and supports explicit Lock PC. Legacy Terminate game remains available only with a non-empty local `games` allowlist. On rule-free PCs, Windows 0.2.10 instead issues a short-lived, single-use target capability for the HA 0.7.2 **Terminate active game** manual button. All gaming policy, quotas, schedules and historical statistics belong in SmartHouse / Home Assistant. The current agent has no local quota enforcement, UI or warning popup. Application enrollment belongs in Home Assistant. An interactive warning popup remains planned; HA-authoritative safe termination is a new development-preview implementation requiring physical Windows acceptance.

## MQTT OTA staging (agent 0.2.10; developer-only)\n\nAn optional, explicitly configured `update.mqtt_staging_enabled` gate can subscribe to device-scoped OTA MQTT 5 topics and save a bounded, SHA-256-matched package to an admin-only staging directory. It requires the separate updater enable flag and pre-created protected `%ProgramData%\\SmartHouseGamingControl\\ota-staging` folder. **No OTA payload is authenticated as a release or passed to the updater; this stage-only gate must not be enabled on family PCs.** Normal deployments are unaffected. See [MQTT OTA design](../docs/mqtt_ota.md).\n\n## MQTT contract

Root: SmartHouse/Gaming/<device_id>/. States and availability are retained; commands must be non-retained. MQTT 5 required (e.g. Mosquitto 2.x), clean start, no persistent command session. Use a separate broker account per PC. The stable device ID is generated automatically and stored in protected ProgramData as `device_id` (or migrated from a legacy `device.id`); the discovery name comes from the current Windows computer name. Do not copy the ID file between PCs.

| Relative topic | Payload | Purpose |
|---|---|---|
| state/uptime | integer seconds | Windows system uptime, every 60 s |
| state/in_game | ON / OFF | At least one configured game process running |
| state/current_game | idle or game names joined by " \| " | Sorted unique display names; split on delimiter for per-game membership |
| state/active_game | one matched game / idle / unknown | Foreground identity (0.2.x preview) |
| state/gaming_active | ON / OFF / UNKNOWN | Foreground activity (0.2.x preview) |
| state/focus_availability | online / offline | Foreground telemetry availability |
| command/terminate_game | PRESS | Force-terminate currently matched games only |
| command/lock_pc | PRESS | Request Windows lock in active interactive session |
| state/terminate_offer | expiring v1 JSON, no PID/path | One-use verified foreground capability; only on rule-free PCs |
| command/terminate_target | strict v1 JSON with token and request ID | HA-requested kill of one current verified tracked app; only on rule-free PCs |
| state/terminate_result | expiring v1 JSON | Non-retained outcome for the corresponding request ID |
| availability | online / offline | MQTT last will and live availability |

Current native MQTT Discovery advertises uptime and Lock PC; the legacy Terminate game button is advertised only on PCs with explicit local `games` rules. Old process-presence discovery entities remain retired. Poll game processes every second by default and publish changes immediately. Republish full sensor snapshot on connect, HA birth and every 60 seconds. The uptime sensor updates every 60 seconds, not each poll. Old prototype discovery entities are removed via empty retained config publications; no migration database is needed. Commands are QoS 0, non-retained, never intentionally replayed; stale queued actions and retained actions are rejected. State and availability use acknowledged retained QoS 1. On reconnect the agent publishes offline, then a fresh complete snapshot, then online; an incomplete snapshot triggers offline and a full retry. Commands remain QoS 0. Verify action results before retrying. Availability does not confirm action completion.

### Foreground activity (agent 0.2.0; preview)

The original process-presence sensors retain their meaning. New retained state topics gaming_active (ON/OFF/UNKNOWN), active_game (one matched game/idle/unknown) and focus_availability distinguish foreground activity from process presence. Metadata advertises focus_protocol=1. A private interactive-session helper samples foreground identity every 250 ms, service polls at most once per second, revalidates session/PID/creation time, refuses stale readings and reports unknown on failures. The Roblox menu counts when focused. No CPU/title/fullscreen heuristics. LocalSystem launches the helper using the selected user's token; named pipe restricts remote connections, checks client PID, and contains no credentials or commands. A local administrator or user tampering with their own helper is outside the threat model. Real service/session tests are mandatory. HA must migrate accounting before production deployment; old HA still charges background process presence.

### Foreground 0.2.1 IPC fix

Standard-user helper requires the original FILE_GENERIC_WRITE pipe ACE plus FILE_READ_ATTRIBUTES (0x00120196). Keep SYSTEM full access, user SID scope and client/server PID verification. Helper failures report a fixed stage and Windows error code in service.log, throttled to once per 30 seconds. Missing or failed samples remain unknown. For physical SYSTEM-to-user testing see [foreground accounting migration](../docs/foreground_accounting_migration.md).

### HA owns policy (current baseline and planned migration)

The existing HA integration uses Recorder current_game transitions and uptime coverage for daily/weekly accounting. The planned 0.5.0 update adds time sensors, an additive Weekend bonus and an automation-facing restriction signal; a separate follow-up will migrate accounting to foreground-only activity. These sensors count running processes, not foreground activity; a minimized game still counts. Unavailable intervals are unknown, not reconstructed, and neither termination nor lock is enforced during network loss. SmartHouse must re-evaluate rules periodically and on reconnect and in_game changes. Agent does not continuously block launch after terminate: HA can issue a fresh command when a game is reopened. HA must avoid treating retained stale sensor state as fresh while unavailable. No local policy automation is installed by the Windows agent.

### Startup diagnostics (agent 0.1.1)

The agent does not persist game state. The rotating service log records initial scan, system uptime, detected process PID, creation time, session ID and executable path on transitions, and confirmed initial MQTT state. It does not log command lines or credentials. A process in the background still counts; the actual reported Roblox startup cause requires real-PC validation. Keep logs local or redact personal paths before sharing.

### Safety and limitations

Legacy manual termination process matching uses configured executable name plus optional exact argument and/or path substring; verify actual installations. With no local `games` rules, the agent rejects **legacy** mass termination but offers a separate one-process targeted manual path through HA 0.7.2. It requires a fresh post-command user helper observation, matching PID/creation time/session/Java signature, OS-process protection and a one-time nonretained MQTT token. A missing/changed/replayed state rejects the request, never guesses a process. Raw foreground telemetry continues independently. It never accepts an arbitrary executable/command from MQTT. Generic Java/Python runtimes require a constraint. Rechecks process identity and match before termination. Forced termination can lose unsaved progress; test disposable worlds. A local administrator can stop the agent. Restrict broker ACLs to the device's state, availability, discovery and command subscriptions; only authorized HA/parent credentials may publish commands. TLS is recommended; example uses plaintext LAN. MQTT availability can be delayed by keepalive.

Lock uses the active console if available, otherwise a single active remote session; if ambiguous or no active interactive session, no lock. LocalSystem service obtains the session user's token and starts a fixed helper in that user's interactive desktop; LockWorkStation initiates an asynchronous lock request, not a verified lock. No passwords or usernames required. The user can unlock Windows normally.

## Build/install (Windows 10/11 x64)

1. Install Python 3.12 on the build PC and run ./build.ps1 -Version 0.2.10 (PowerShell). The standalone onedir build is under dist/SmartHouseGamingControl/. Target PC does not need Python.
2. Copy config.example.yaml to config.yaml and set broker/credentials; never commit secrets. `device.id`, `device.name` and `games` are not required. A rule-free agent reports raw foreground activity to HA and offers Lock PC, but does **not** accept legacy Terminate game. With compatible HA 0.7.2, a distinct **Terminate active game** button can safely target one currently tracked foreground process when verified; physical validation is pending. Existing PCs can keep local `games` temporarily for safe manual termination (#155). Run from elevated PowerShell: Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'javaw|minecraft|roblox' } | Select-Object Name,ExecutablePath,CommandLine. Don't share command lines containing credentials.
3. Close valuable game sessions. Run ./install.ps1 as Administrator. Service runs as LocalSystem (required for WTSQueryUserToken); program in Program Files and config/logs/identity file in protected ProgramData. Keep `device_id` during upgrades and reinstallations. If upgrading a legacy configuration, its existing `device.id` is persisted and preserved; subsequent host renames affect only the reported default name, not HA identity or MQTT topics. Installer expects a fresh install.
4. Check the native MQTT device advertises Uptime and Lock PC. When no `games` rules exist, the old Terminate game must be absent/unavailable while the new HA-owned **Terminate active game** appears only for a freshly verified tracked foreground app. With legacy rules, the original Terminate game remains; test either button only on disposable sessions after review. Verify fresh raw foreground in HA, lock, reboot and reconnect. No autonomous restrictions should occur. See docs/acceptance.md.
5. Stop-Service SmartHouseGamingControl stops the agent; ./uninstall.ps1 removes service registration and preserves config/logs.

## Validation

Unit tests mock external process/Windows/MQTT operations; CI covers Windows and Linux. Actual Windows service, MQTT 5 broker, PyInstaller build and interactive lock/termination require real-PC acceptance testing. Not deployed.

## Planned user experience

Application enrollment will allow parents to capture a live foreground application in HA Configure → Application list and assign a friendly name, without maintaining a mandatory catalog. The Windows warning popup will display HA-authoritative remaining time with a draining progress bar, 60/10/1/0 minute alerts and the footer Powered by HAL Systems. Both are backlog items, not current agent capabilities. See [product direction](../docs/product_direction.md).
