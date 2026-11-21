# Parental Control — clean-start migration (issue #4 / #67)

**Owner decision (2026-11-21):** Test-only Parental Control usage history
does **not** need preserving. For the first coordinated v2 deployment,
start again with new HA-owned activity entities and verified usage intervals.
This supersedes the historical entity-ID adoption procedure.

**Scope:** Only the two **explicitly selected Parental Control gaming PCs**
and their verified historical Gaming/Parental Control entity IDs. **Never**
wipe HA's complete Recorder database or purge unrelated lights, climate,
energy, other PCs or house services. No deletion happens automatically on
upgrade, restart or reading this document.

## One-time maintenance plan

1. Identify the actual TrueNAS-associated HA and authorized Windows
   gaming PC. Record installed SHA/version, MQTT discovery mode and device
   ID. Keep restrictions/auto lock and termination **disabled**. Stop the
   selected Windows gaming agent during the reset. Do not deploy to the
   second PC until the first pilot passes.
2. Capture a *rollback* backup of HA config-entry options (limits,
   `tracked_apps`, MQTT setup), Recorder, existing registry and the Windows
   agent version/config. These backups are optional for *retention* but
   useful if the reset/deployment fails. No secrets in public issues.
3. **Before removing registry entries**, make an explicit per-device list
   of *all* old Parental Control entity IDs, including native MQTT, direct
   MQTT, budgets, duration/usage sensors, switches and any previously
   renamed or removed gaming IDs known from Recorder. Confirm every
   entity belongs to the selected PC. Avoid guesses and wildcard patterns.
4. Unload the specific Parental Control HA config entry. If an earlier v2
   preview had already stored confirmed intervals, invoke the explicitly
   guarded maintenance function
   `fresh_start.async_reset_confirmed_intervals(hass, entry,
   confirm_device_id="<verified device ID>")` in an authorized HA
   maintenance context. It rejects a loaded entry, wrong PC and corrupt
   data; it clears only that entry's **v2 confirmed-interval checkpoint**,
   not options or other PCs. A first-time installation with no cutover
   already has an empty ledger and needs no reset. Do this **once**, not
   on normal updates.
5. While old sources are stopped, in HA **Developer Tools → Actions** use
   the official `recorder.purge_entities` action with `keep_days: 0`
   and only the **exact, reviewed** entity IDs from step 3. Example YAML
   (replace with the real selected gaming entity IDs; *not* a copy-paste
   action for arbitrary devices):

   ```yaml
   action: recorder.purge_entities
   data:
     keep_days: 0
     entity_id:
       - sensor.example_gaming_pc_old_active_game
       - sensor.example_gaming_pc_old_current_game
       - binary_sensor.example_gaming_pc_old_in_game
   ```

   Add all confirmed Gaming/Parental Control history entities for that
   selected device to the explicit list. Check Recorder has completed
   the queued purge. Do **not** call global `recorder.purge`, delete the
   shared database file, use `domains: [sensor]`, or broad globs.
6. Install the reviewed compatible **HA 0.5.5 + Windows agent 0.2.6**
   source/build on the authorized pilot only. Windows sends non-retained
   raw `foreground_identity` v2 and retires its exact legacy native MQTT
   activity discovery topics. Verify old MQTT registry entries disappear
   and cannot be re-advertised. For previous scoped HA legacy entries,
   the gated exact-owner `legacy_activity_cleanup.async_retire` helper
   can retire them only after source/old-agent verification. This cleanup
   preserves the **new** HA-owned `Active game` sensor.
7. **Do not capture or adopt any old `Active game` entity ID.** The new
   HA-owned sensor gets a fresh unique ID (`<device>_active_game`) and
   may receive a different entity ID if HA has collisions. Once old
   entities are gone, verify and optionally rename the new entity in HA
   to the desired friendly ID. No old Recorder continuity is required.
8. For each PC's first new setup, open **Settings → Devices & services →
   SmartHouse Parental Control → Configure → Tracked applications**.
   Remove obsolete test aliases if any. Run Minecraft/Roblox (or any
   desired game), select its **fresh** raw executable + vetted Java
   class/JAR/module discriminator, then add a friendly HA name. **Never**
   auto-import old Windows `games` rules. This list lives only in that
   PC's HA `options.tracked_apps` and **persists across later upgrades**;
   do not repeat enrollment on the second and later updates.
9. Validate live foreground Alt+Tab/game→browser/minimize, `idle` vs
   `unknown`, reconnect, HA restart, two-PC isolation, current day/week,
   one-time initialization, historical checkpoint starting at zero,
   stable alias names, manual buttons and no duplicate entities. Unknown
   periods remain incomplete, not false idle. Do not enable automatic
   enforcement on incomplete coverage.
10. Record actual installed SHAs and pilot PASS/FAIL for #56. If anything
    fails, stop and roll back; do not touch the second PC or unrelated HA
    services. This document does not claim the live cleanup/deploy ran.

The Recorder purge removes historical state rows of the specified entities.
The separate verified-interval checkpoint is intentionally reset in step 4.
**Neither occurs automatically.** The stable per-PC mappings created after
clean start continue to survive future HA updates.
