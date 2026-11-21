# Issue #4 — first enrollment, migration and one-PC acceptance

The production source cutover is gated on all required PRs and real device
acceptance; **do not deploy unfinished core libraries as a feature**.

## Owner-facing behavior at the next integrated deploy

1. After installing the compatible Windows v2 agent + HA integration, open
   **Settings → Devices & services → Parental Control → Configure → Tracked applications**
   for each associated gaming PC. The new HA-owned list intentionally starts
   empty if the PC has never used this configuration. Legacy Windows rules
   MUST NOT be automatically imported.
2. Start one desired game, observe the fresh raw executable + safe argument
   signature on the right PC, click **Add application**, choose a readable
   name such as Minecraft or Roblox, and save. Java must include a verified
   class/JAR/module discriminator; bare java.exe/javaw.exe is not enough.
3. Add any other games the same way. Rename/Remove stays entirely within
   the HA config entry; no Windows config changes, service restarts, or
   automatic terminate/lock are side effects of enrollment.
4. HA persists the mapped raw identity and display name in the selected
   config entry's `options.tracked_apps`. From the **second** version update
   onward, reopening Configure is optional: previously saved applications
   remain installed and retain their names. Back up HA config entries/options
   during each upgrade and verify a restart/update roundtrip.
5. An unconfigured valid focused process is not charged as tracked gaming.
   Offline, unsupported, stale or ambiguously identified runtime is
   **unavailable/unknown**, never a confirmed idle sample.
6. Account only current-day and current-week verified foreground intervals;
   old Recorder rows must remain untouched. Unknown previous periods cannot
   be silently backfilled or counted as idle. Manual Lock PC / Terminate game
   buttons remain available where originally advertised.

## Staged GO/NO-GO test matrix (source + installed evidence)

| Gate | Required demonstration | Failure action |
| --- | --- | --- |
| Source | Exact reviewed SHA, versions, 8/8 CI, 90% coverage | NO-GO |
| Backup | TrueNAS-associated HA config entries/options, entity IDs, Recorder and agent rollback | NO-GO |
| Setup | First HA enrollment Minecraft Java + Roblox on chosen PC | NO-GO if mixed with legacy names |
| Persistence | HA reload, restart, new component version retain apps and aliases | Roll back HA |
| Live state | Alt+Tab/game→browser/lock/offline, stale/replay protection | No cutover |
| Timing | Current day/week, DST/week boundary, crash and unknown gaps | Disable restrictions, no automatic commands |
| Isolation | Second PC cannot claim first PC's raw topics, mappings or history | Roll back |
| Discovery | Only verified redundant entities retired, Active game identity retained | Block cleanup |
| Safety | No autonomous terminate/lock MQTT; explicit buttons still function in safe mock | NO-GO |
| Pilot | TrueNAS project + one authorized Windows PC (not other HA sites) | Stop and report |

Actual host inventory, signing, service recovery and the second PC require
the separate controlled deployment process in #56 and explicit owner approval.
Keep private infrastructure, credentials and child identifiers out of public
CI fixtures and PR comments. A synthetic test harness is not proof of a
successful live installation.

Current synthetic tests: `tests/home_assistant/test_foreground_e2e.py`.
