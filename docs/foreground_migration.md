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

## Native MQTT Active game entity ID preservation — manual guarded steps

This procedure must be carried out only by the authorized deployment
operator. Code support is in `active_game_identity.py`; the helper is
**never invoked on HA startup or background discovery**.

1. While the **old MQTT Active game entity still exists**, call
   `async_capture_native_active_game(hass, entry)` for the exact device.
   This durably captures its existing `sensor.*` entity ID under that
   entry's HA storage. It refuses missing or ambiguous ownership.
2. Upgrade the verified TrueNAS-associated HA integration to the reviewed
   HA v2 foreground source. Deploy the compatible Windows native discovery
   retirement build to **one PC only** after the agent has passed security
   and rollback checks. Confirm exact tombstones for old agent-owned
   activity sensors and no re-advertisement by legacy agents.
3. Wait until the old native `sensor.*_active_game` MQTT registry entry is
   actually unregistered. Verify the new HA-owned entity is registered,
   belongs to the expected config entry, and no unrelated entity occupies
   the historic entity ID.
4. Call `async_adopt_native_active_game(hass, entry,
   legacy_retired=True)` **only** after independently verifying these
   conditions. This moves the HA-owned entity to the original entity ID,
   preserving existing Recorder history by key. It refuses collisions,
   cross-device ownership, or absent checkpoints. The operation is
   idempotent on repeated, verified invocation.
5. Inspect the device page and history. If old agent re-advertises native
   topics, a collision appears, or the entity ID/history cannot be
   preserved, **STOP** and use the prepared rollback procedure; never
   delete Recorder rows or try wildcard registry deletions.

The helper's boolean `legacy_retired` is a manual operator assertion,
NOT independent proof of safe production migration. This does not
constitute a successful real-device deployment or a finished #56.
