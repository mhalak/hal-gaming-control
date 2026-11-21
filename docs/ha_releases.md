## 0.5.6 — streamline per-PC Configure menu

- Show only **MQTT configuration** (read-only) and **Tracked applications** (one form, immediate HA save).
- The editor now displays **Currently detected application** from a fresh v2 `foreground_identity` MQTT snapshot (safe executable basename and Java discriminator only), **Raw sensor value**, **Displayed as** from HA mappings (`idle` for untracked executables, `unavailable` for missing/ambiguous status), then **Application List**. A mismatching candidate is not offered as a new app. Native HA forms do not push live changes while open: close/reopen after changing the PC foreground; new Add revalidates the latest token before save. Remove legacy Restrictions and schedule, Windows update settings and redundant top-level Save steps and their obsolete translation entries.
- No options migration, no clearing stored daily/weekly limits, schedule/enablement, legacy actions, per-game settings or approved updater URL. An already-enabled rule still follows saved policy. The remote update entity and manual Lock PC / Terminate game actions remain unchanged. Nothing is written to Windows, and no automatic commands are introduced.
- Update real Home Assistant flow tests for the two-entry menu, persisted legacy options and application editor save. HA-only patch version; Windows agent remains 0.2.6.
- The owner observed a missing `{actions}` translation variable on a deployed Configure screen. Current source strings do not contain that placeholder; after deployment verify the installed HA build and refresh frontend translations/cache rather than treating that stale error as proof of a remaining source string.
- Requires CI review and separately coordinated deployment; no live installation is claimed.

## 0.5.5 — single-page Tracked applications editor

- Replace the three Add/Rename/Remove submenus with a single native HA multiple-object editor. Current HA-owned mappings are prepopulated as removable/editable rows. Each row displays its **actual, safe Windows executable basename** plus a vetted Java main-class/JAR/module signature where available. New-row default selects the last fresh foreground candidate; user supplies a friendly name.
- Never enroll an arbitrary process typed by the browser: backend validates every row against current HA mappings or the unchanged, fresh, per-device non-retained candidate token. Duplicate/forged/ambiguous Java identities and concurrent app-list edits fail closed; other options and historic stable accounting identities are preserved. No Windows config writes.
- Native HA Object Selector supports structured multi-item Add/Remove controls without any HACS/custom frontend. Reopen Configure to refresh foreground detection. This is a HA-only UI update: Windows agent remains 0.2.6.
- New candidate UI is not auto-discovery of all games and does not auto-add an application just because its process is in foreground. Observed unconfigured Roblox correctly reports idle.
- Requires 8/8 CI and controlled HA deployment after reviewed build SHA. Clean-start migration remains an optional, one-time action, not repeated on updates.

## 0.5.4 — clean-start gaming history (test-only owner migration decision)

- Owner explicitly opted to discard past Gaming/Parental Control Recorder history. There is **no need to preserve old native Active game entity IDs**. Removed the unused explicit native-ID capture/adoption module and its tests.
- A guarded, *operator-invoked only* v2 confirmed-interval reset is available for one selected **unloaded** HA entry. Existing app mappings, limits, settings, other PCs and Home Assistant Recorder remain unchanged by that helper.
- One-time manual **Recorder purge_entities** with `keep_days: 0` and an owner-reviewed list of exact old gaming entity IDs discards the legacy history; never `recorder.purge`, global database deletion or broad sensor globs.
- Gated exact-owner native tombstone helper now includes the obsolete Windows native MQTT `Active game` discovery topic, while scoped cleanup explicitly **keeps** the new HA-owned Active game.
- First coordinated install of compatible Windows 0.2.6 + HA 0.5.4 starts a new confirmed-foreground ledger; add desired applications once in HA Configure, then preserve `options.tracked_apps` through later upgrades. No automatic history reset on update and no live deploy claimed.
- Previous 0.5.2/0.5.3 historical notes about retaining Recorder entity IDs describe their *old* design and are superseded by this clean-start decision. See `docs/foreground_migration.md`.

## 0.5.3 — retire scoped legacy activity entities (code candidate)

- HA-owned Active game remains the single user-facing application state; new current-day/current-week time sensors derive from the confirmed v2 ledger. The old direct MQTT entity classes Current game / In game / Gaming active and legacy v1 foreground adapter are no longer instantiated or shipped. Agent-side native discovery retirement is allocated to Windows 0.2.6.
- Existing HA registry entries from previous installed versions must be handled only through the strictly gated exact-owner helper after verified cutover and agent native discovery retirement. Do not broadly delete registry entries or Recorder history. Native Active game entity ID adoption must capture old ID before tombstone; no automatic migration or deployment has happened.
- This is an independent source candidate. Preserve per-PC options.tracked_apps through upgrades; first migration prompts one-time manual game enrollment, later updates require no re-enrollment. Validate full 8/8 CI, built SHA and safe TrueNAS-associated HA / one-Windows-PC pilot via #56.

## 0.5.2 — HA-owned foreground integration (source candidate; staged migration pending)
- Source code uses per-PC raw non-retained v2 `foreground_identity` with HA-owned `options.tracked_apps` aliases; first compatible deployment requires manual one-time application enrollment, later HA upgrades keep the saved mappings.
- Confirmed-only foreground segments are saved per config entry and explicit cutover epoch, retaining recorded raw stable identities through rename/remove. No inferred activity during offline or stale intervals; current-day/week sensors mark historical gaps incomplete. Old Recorder history remains untouched.
- HA Active game now gets its name from the configured HA aliases rather than old Windows game strings. Both native and direct MQTT modes are covered in automated tests.
- **Important: Not a coordinated deployment by itself.** Legacy native MQTT discovery and duplicate/retired activity entities require controlled cross-component migration and compatible Windows agent update before any production rollout (#4/#67/#56). No automatic restrictions are enabled. Validate actual installed version/build SHA and rollback evidence.

# HA integration release history

The HA integration version is the `version` in `custom_components/smarthouse_gaming/manifest.json`, displayed by Home Assistant. Increment this version for every deployable HA change: minor for features, patch for fixes, major for breaking changes as appropriate. Record changes here, deploy latest main and record the deployed commit for rollback. Windows agent releases have separate versioning; do not bump Windows for HA-only changes. A manifest version is not a published GitHub Release.

## 0.5.1 — Parental Control Preview 3 (candidate, not yet verified as deployed)
- #7 / #52 incremental read-only foreground candidate detection. The Windows 0.2.4 agent publishes only a bounded executable basename, a vetted Java launch signature (main class, JAR basename or module), and a short-lived opaque token on a non-retained MQTT 5 topic. HA displays a recent candidate in the selected PC's Tracked applications menu, including apps not already monitored. It rejects retained/stale, foreign-device and malformed messages. Neither side transmits the raw command line or credentials, window title, PID or executable path; ambiguous Java entry points are shown without falsely naming a game.
- HA Options Flow now supports **Add/Rename/Remove** for HA-managed application aliases keyed by safe executable + Java signature, stored only in the selected device's HA entry options. Add requires a fresh unchanged candidate token; ambiguous bare Java cannot be enrolled. Duplicate and concurrent app-list edits are rejected; other options, limits and Windows configuration are preserved. Earlier Windows agents simply show no candidate.\n- **Not yet active in the running HA Active game sensor:** alias normalization and foreground-only counting require the #4 source cutover and compatibility tests; this CRUD feature is not Windows rule synchronization or automatic enforcement.
- HA 0.5.1 and Windows 0.2.4 are **independent source/package candidates**, not proof of installation; validate each host build SHA, checks and Windows trust restrictions before deploying via #56.

## 0.5.0 — Parental Control Preview 2 (candidate, not yet verified as deployed)
- #50: installed HA integration version diagnostic and optionally staged source SHA.
- #51: remove legacy Add/Remove action selectors and the coordinator's automatic MQTT termination/locking path. Preserve explicit manual buttons and stored legacy options for rollback; no replacement default automation.
- #54: opt-in additive Weekend bonus **calculation kernel** and exact non-destructive legacy migration preview. The existing Weekend daily limit control remains; no bonus slider or automatic migration yet.
- #55: read-only shared HA MQTT connection diagnostics with validated broker/port, never displaying secrets or writing to broker settings.
- This is a preview **source/package version**, not a report of a completed deployment. Do not claim a functional 0.5.0 gaming-time sensor, restriction binary sensor, foreground-only time accounting, tracked app enrollment or Windows countdown popup: those remain open (#3/#4/#7/#52).
- This integration change is a minor increment from 0.4.3 because the UI/enforcement contract changes. Windows version is independently allocated to 0.2.3 for reviewed packaging/provenance, not because HA features run on Windows.
- Deployment requires #56 TrueNAS-hosted HA validation, previous-state backup, safe restart, no automatic destructive actions and post-deploy reporting.

## 0.4.3 (scoped foreground telemetry candidate)
- Add Active game and Gaming active entities when HA MQTT discovery is disabled. Preserve native discovery entities, legacy process-presence telemetry and commands.
- Gate scoped foreground display on supported metadata, agent/focus availability and a consistent enrolled game/active pair; clear cached values on offline/disconnect. No inference from legacy process presence.
- This is telemetry support only. Current accounting/enforcement remains unchanged; freshness, Recorder migration boundary and full foreground-only accounting remain issue #4. No release or deployment authorization.

## 0.4.2 (publication preparation)
- Rename the public-facing integration to SmartHouse Parental Control while keeping its domain and device identities.
- Add MQTT configuration information to the Options Flow; broker editing remains in HA's built-in MQTT integration.
- Temporarily withdraw the per-game limit editor and public feature claims while its UX is redesigned. Existing stored per-game limits and their current enforcement semantics are preserved; hiding the editor does not disable legacy rules.
- Prepare HACS packaging and public release documentation. No change to stable accounting or Windows binaries.

## 0.4.1
- Restore disabled/fallback selection directly on all three limit sliders. The aligned -10 slider position maps to the existing stored -1 sentinel (no daily/weekly limit; weekend falls back to daily). Zero still disallows play. All existing values, identities and policy semantics are preserved.

## 0.4.0
- Per-PC diagnostic Windows agent version sensor displays the last reported installed version from retained MQTT discovery metadata, independently of remote update configuration or PC availability. Unknown until valid version metadata arrives. No Windows agent update needed.

## 0.3.0
- Per-device Add 30 minutes button: cumulative same-local-day bonus, expires at midnight, persisted across restarts; weekly, schedule and per-game limits unaffected.
- Native daily, weekend daily and weekly limit sliders (0–600 min, step 10). Existing values preserved; legacy disabled/out-of-range values remain unchanged and show unknown until edited. Zero blocks play. Advanced restrictions settings can reset a limit to -1.
- Add/remove action selectors under Configuration, unique actions in configured order; reorder in Options Flow. No automatic execution when editing an action itself; normal enforcement still applies.
- All gaming settings apply live without reloading; only catalog/device metadata changes require reload.
- Budget sensors retain native Sensors grouping; HA does not expose custom device page categories. Bonus/limit/usage minute attributes support dashboards.

## 0.2.0
- Per-device persistent Unlimited gaming switch, independent of PC availability; no integration reload on toggle.
- Remove the combined weekend limit; retain weekend daily override and weekly quota including weekends.
- Preserve Recorder accounting and configuration. Live override bypasses automatic restrictions; turns off without resetting time.
- Includes previously merged brand icon and daily/weekly remaining budget sensors.

## 0.1.0
- Initial HA integration and Windows agent protocol; intermediate development deployments shared this version.
