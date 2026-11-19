# SmartHouse Parental Control — Windows MQTT agent

For an end-user installation, manual upgrade, rollback and troubleshooting, follow the [Windows deployment guide](../docs/windows_deployment.md). This document describes the underlying service and protocol. The foreground-enabled build is an unvalidated development candidate; do not deploy it as a stable release.

The Windows service reports five sensors and executes two explicit actions. All gaming policy, quotas, schedules and historical statistics belong in SmartHouse / Home Assistant. The current agent has no local quota enforcement, UI or warning popup. Application enrollment and an interactive warning helper are planned separately.

## MQTT contract

Root: SmartHouse/Gaming/<device_id>/. States and availability are retained; commands must be non-retained. MQTT 5 required (e.g. Mosquitto 2.x), clean start, no persistent command session. Use a separate device ID and broker credentials per PC.

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
| availability | online / offline | MQTT last will and live availability |

Seven MQTT Discovery entities (5 telemetry sensors, 2 buttons). Poll game processes every second by default and publish changes immediately. Republish full sensor snapshot on connect, HA birth and every 60 seconds. The uptime sensor updates every 60 seconds, not each poll. Old prototype discovery entities are removed via empty retained config publications; no migration database is needed. Commands are QoS 0, non-retained, never intentionally replayed; stale queued actions and retained actions are rejected. State and availability use acknowledged retained QoS 1. On reconnect the agent publishes offline, then a fresh complete snapshot, then online; an incomplete snapshot triggers offline and a full retry. Commands remain QoS 0. Verify action results before retrying. Availability does not confirm action completion.

### Foreground activity (agent 0.2.0; preview)

The original process-presence sensors retain their meaning. New retained state topics gaming_active (ON/OFF/UNKNOWN), active_game (one matched game/idle/unknown) and focus_availability distinguish foreground activity from process presence. Metadata advertises focus_protocol=1. A private interactive-session helper samples foreground identity every 250 ms, service polls at most once per second, revalidates session/PID/creation time, refuses stale readings and reports unknown on failures. The Roblox menu counts when focused. No CPU/title/fullscreen heuristics. LocalSystem launches the helper using the selected user's token; named pipe restricts remote connections, checks client PID, and contains no credentials or commands. A local administrator or user tampering with their own helper is outside the threat model. Real service/session tests are mandatory. HA must migrate accounting before production deployment; old HA still charges background process presence.

### Foreground 0.2.1 IPC fix

Standard-user helper requires the original FILE_GENERIC_WRITE pipe ACE plus FILE_READ_ATTRIBUTES (0x00120196). Keep SYSTEM full access, user SID scope and client/server PID verification. Helper failures report a fixed stage and Windows error code in service.log, throttled to once per 30 seconds. Missing or failed samples remain unknown. For physical SYSTEM-to-user testing see [foreground accounting migration](../docs/foreground_accounting_migration.md).

### HA owns policy (current baseline and planned migration)

The existing HA integration uses Recorder current_game transitions and uptime coverage for daily/weekly accounting. The planned 0.5.0 update adds time sensors, an additive Weekend bonus and an automation-facing restriction signal; a separate follow-up will migrate accounting to foreground-only activity. These sensors count running processes, not foreground activity; a minimized game still counts. Unavailable intervals are unknown, not reconstructed, and neither termination nor lock is enforced during network loss. SmartHouse must re-evaluate rules periodically and on reconnect and in_game changes. Agent does not continuously block launch after terminate: HA can issue a fresh command when a game is reopened. HA must avoid treating retained stale sensor state as fresh while unavailable. No local policy automation is installed by the Windows agent.

### Startup diagnostics (agent 0.1.1)

The agent does not persist game state. The rotating service log records initial scan, system uptime, detected process PID, creation time, session ID and executable path on transitions, and confirmed initial MQTT state. It does not log command lines or credentials. A process in the background still counts; the actual reported Roblox startup cause requires real-PC validation. Keep logs local or redact personal paths before sharing.

### Safety and limitations

Process matching uses configured executable name plus optional exact argument and/or path substring; verify actual installations. It never accepts an arbitrary executable/command from MQTT. Generic Java/Python runtimes require a constraint. Rechecks process identity and match before termination. Forced termination can lose unsaved progress; test disposable worlds. A local administrator can stop the agent. Restrict broker ACLs to the device's state, availability, discovery and command subscriptions; only authorized HA/parent credentials may publish commands. TLS is recommended; example uses plaintext LAN. MQTT availability can be delayed by keepalive.

Lock uses the active console if available, otherwise a single active remote session; if ambiguous or no active interactive session, no lock. LocalSystem service obtains the session user's token and starts a fixed helper in that user's interactive desktop; LockWorkStation initiates an asynchronous lock request, not a verified lock. No passwords or usernames required. The user can unlock Windows normally.

## Build/install (Windows 10/11 x64)

1. Install Python 3.12 on the build PC and run ./build.ps1 -Version 0.2.1 (PowerShell). The standalone onedir build is under dist/SmartHouseGamingControl/. Target PC does not need Python.
2. Copy config.example.yaml to config.yaml and set broker/credentials; never commit secrets. Confirm game names, paths and arguments on actual installations. Run from elevated PowerShell: Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'javaw|minecraft|roblox' } | Select-Object Name,ExecutablePath,CommandLine. Don't share command lines containing credentials.
3. Close valuable game sessions. Run ./install.ps1 as Administrator. Service runs as LocalSystem (required for WTSQueryUserToken); program in Program Files and config/logs in protected ProgramData. Installer expects a fresh install.
4. Check the native MQTT device has seven advertised entities (five telemetry entities, two actions); scoped HA onboarding still uses the legacy telemetry contract. Verify sensors, terminate on a disposable game session, lock, reboot, reconnect. No autonomous restrictions should occur. See docs/acceptance.md.
5. Stop-Service SmartHouseGamingControl stops the agent; ./uninstall.ps1 removes service registration and preserves config/logs.

## Validation

Unit tests mock external process/Windows/MQTT operations; CI covers Windows and Linux. Actual Windows service, MQTT 5 broker, PyInstaller build and interactive lock/termination require real-PC acceptance testing. Not deployed.

## Planned user experience

Application enrollment will allow parents to capture a live foreground application in HA Configure → Application list and assign a friendly name, without maintaining a mandatory catalog. The Windows warning popup will display HA-authoritative remaining time with a draining progress bar, 60/10/1/0 minute alerts and the footer Powered by HAL Systems. Both are backlog items, not current agent capabilities. See [product direction](../docs/product_direction.md).
