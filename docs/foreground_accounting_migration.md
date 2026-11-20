# Foreground accounting migration — release gate

Agent 0.2.0 exposes process presence and a separate foreground pair. HA 0.3.0 UI work is separate; do not deploy this agent alone as a solution for accounting. HA follow-up must subscribe to both new states in scoped and native MQTT mode; account only periods of one valid active_game with gaming_active ON, masked by existing uptime coverage and unknown gaps. No fallback to current_game/in_game for accounting after migration. Reevaluate active-game and live pair consistency before enforcing; preserve explicit manual controls. Keep device IDs/configuration/options and old telemetry history. Historical process-presence intervals are not reliable active time: disclose the migration boundary; do not charge them as foreground activity. Existing old agents must report budget unavailable until compatible telemetry arrives. Test both modes, two simultaneous games and Alt+Tab, idle/unknown/lock/reconnect/restart, native MQTT downgrade or stale retained messages, Recorder restart and boundaries, and regress v0.3.0 features. Do not release or deploy this candidate until full CI, actual LocalSystem interactive probe tests and the HA accounting follow-up are reviewed. Physical acceptance: prove foreground transitions with disposable sessions, no unexpected action execution; preserve config and roll back binaries if needed.


## 0.2.1 — confirmed named-pipe permission fix

Observed in a Windows development test: original packaged helper failed CreateFile (Win32 error 5); an isolated temporary pipe using user mask 0x00120196 successfully delivered eight valid Roblox foreground samples. The existing production installation remained 0.1.1. The isolated result does not prove full service/MQTT acceptance.

The user ACE is now FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES, no broader principals. Exit codes convey a fixed stage and Win32 code; the parent logs errors at most once per 30 seconds. No policy changes.

### Real SYSTEM-to-standard-user IPC test

Build the packaged agent with build.ps1 -Version 0.2.1. In an explicitly authorized test on a logged-in, unlocked Windows test PC, run pytest as LocalSystem with the environment variable SMARTHOUSE_FOCUS_SYSTEM_TEST_EXE pointing at the absolute path of the actual packaged SmartHouseGamingControl.exe:

    python -m pytest -q tests/test_focus_system_ipc.py

This opt-in test requires a real non-elevated interactive user and SYSTEM runner; ordinary CI skips it. It launches the packaged helper via the actual FocusProbe._start path, checks fresh samples through the real named pipe including PID validation, closes the helper and pipe in finally, and never sends MQTT or control commands. Do not downgrade security or grant broader permissions to make it pass. Record output and then run the full service acceptance with restrictions disabled: focus transitions, minimize/restore, lock/unlock, restart and MQTT unknown behavior. Roll back to working 0.1.1 if acceptance fails.

## Current integration follow-up

The foreground migration tracks the missing HA foreground entities in scoped MQTT mode and migration of daily/weekly totals and restriction evaluation. The planned HA 0.5.0 budget update changes the budget model to Daily limit + applicable Weekend bonus + same-day bonus, with an independent Weekly limit, and moves action execution to HA automations. It does not change the accounting source. Preserve these interfaces during migration. Application enrollment will subsequently allow enrollment of arbitrary monitored foreground applications. See [product direction](product_direction.md).


## Paired history normalization increment

The isolated normalization helper combines the two HA state-transition histories from an explicit cutover timestamp. A confirmed idle requires both idle and off; confirmed play requires on and one enrolled non-reserved application name. Inconsistent, missing or invalid states are unavailable. Apply simultaneous transitions together, with last observation winning at the same timestamp. Do not import pre-cutover state anchors. Existing uptime coverage can mask unobserved intervals, but neither paired values nor heartbeat coverage alone proves retained-message freshness or a safe post-reconnect state. This helper remains unused by production accounting until the durable boundary, freshness, real Recorder and migration behavior are validated.


## Atomic foreground snapshot — proposed transport contract

Legacy retained active_game/gaming_active/focus_availability values remain diagnostic, not evidence of a fresh sample. A new device-scoped topic `SmartHouse/Gaming/<device_id>/state/foreground_snapshot` will carry one non-retained JSON packet: version (integer 1), device_id, epoch (32 lowercase hexadecimal digits identifying a new connection generation), sequence (positive increasing integer), observed_at (UTC Unix seconds for the observation, not the delivery), active_game and gaming_active. The pair is either a single enrolled application and ON, idle and OFF, or unknown and UNKNOWN. No process paths, PIDs, window titles or command lines belong in a packet.

The pure HA consumer rejects non-live, malformed, stale, inconsistent, wrong-device and out-of-order packets; duplicate packets do not prolong a sample. The freshness window is 10 seconds from observation, with up to 2 seconds future clock skew (no additional lifetime). A monotonic deadline accounts for already elapsed sample age. Disconnect invalidation preserves in-memory ordering watermarks, including recent retired epochs; HA restart recreates them. Synchronized Windows/HA clocks, authorized device-topic ACLs and reliable live publication are prerequisites. This is not cryptographic publisher authentication or durable replay protection across HA restarts.

Publisher and MQTT subscriber integration remain future increments. Periodic observations must be emitted even when the game is unchanged, without replaying a previous sample on reconnect. Unknown, disconnect and expiry must produce explicit coverage gaps before the accounting coordinator can consume this stream. Native and scoped modes must share the same validated accounting source. The new gate is isolated and does not yet alter runtime sensors, budgets or commands.
