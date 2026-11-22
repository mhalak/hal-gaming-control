## 0.5.13 — native per-PC gaming schedule controls

- Each PC now has **Schedule enabled**, **Allowed from**, and **Allowed until** in its Home Assistant Configuration section, using native editable Time entities. Stored settings are retained; defaults are off and 16:00–20:00.
- These are **hours when playing is allowed**, not a scheduled command. Outside the window the passive Gaming restriction sensor adds `schedule` to its reasons, only if Gaming rules enabled and Schedule enabled are both ON, Unlimited gaming is OFF, and live accounting is verified.
- Overnight intervals work (20:00–02:00); the end time is exclusive. Equal start/end means all-day permission. Windows are evaluated in HA local time, including DST transitions. Options update live without resetting Recorder accounting or tracked applications.
- No automatic game closing, locking, or default automation; no custom UI. HA 0.5.13; Windows 0.2.6 unchanged. Physical deployment acceptance separate.

## 0.5.12 — passive per-PC Gaming restriction signal

- Add **Gaming rules enabled**, a per-PC HA-local switch (default OFF) that controls whether the existing rule engine evaluates restrictions. It never issues MQTT commands. **Unlimited gaming** still provides an independent live bypass.

- New `binary_sensor.<pc>_gaming_restriction` reports **ON** when current verified gaming totals violate Daily budget, Weekly budget, schedule, or an active game's per-game budget. **OFF** means no applicable restriction; **unavailable** means there is not enough fresh verified accounting to decide.
- The sensor exposes ordered `reasons` (e.g. `daily`, `weekly`, `schedule`, `game:Roblox`) and the first `reason`. It respects the additive Weekend and date-scoped Parent bonuses, plus Unlimited gaming and the enabled flag.
- Runs in both direct-MQTT and native-MQTT configurations; tied to its own Windows PC device. It is only an observation **and never calls Terminate game or Lock PC**.
- A parent-authored automation must check restriction **and** Active game, and re-evaluate on restriction changes, new foreground games and HA startup. If data becomes unavailable, do not treat it as permission for an automatic destructive action.
- No automatic enforcement, default automations, Windows agent updates, migration of stored playtime or registry deletion. HA 0.5.12, Windows agent 0.2.6. Physical HA and PC acceptance remain separate.

## 0.5.11 — clean-preview budget names, additive Weekend bonus and readable durations

- Replace the old **Daily limit**, **Weekly limit** and **Weekend daily limit** configuration entities with fresh **Daily budget**, **Weekly budget** and **Weekend bonus** entities. New `number` IDs end in `_daily_budget`, `_weekly_budget` and `_weekend_bonus`. Remove only the obsolete project-owned limit entity registry entries.
- **Daily budget:** 0–600 min in 10-minute steps, with the existing -10 no-limit slider position mapped to internal -1. **Weekly budget:** 0–4200 min in 60-minute steps; 0 is a real finite budget. Fresh installs default to weekly 4200 min while restrictions remain off; existing weekly -1/no-limit is not coerced into 0 or silently enabled, and the parent must select a valid weekly slider value if desired. Legacy off-grid values are preserved until edited.
- **Weekend bonus:** 0–600 min in 10-minute steps, added to finite Daily budget on Saturday *and* Sunday. It does not increase Weekly budget. The previous `weekend_daily` stored value is not migrated or interpreted; when no new bonus has been configured, the bonus is **0**. Manual weekend edits discard obsolete weekend override keys. This is a deliberate fresh-preview behavior change; review budgets before enabling automations.
- Rename percent sensors to **Daily budget remaining** and **Weekly budget remaining** with new unique IDs ending in `_daily_budget_remaining` / `_weekly_budget_remaining`, to avoid duplicate names. They still represent percentages. Their attributes use `budget_minutes` and, for daily only, `parent_bonus_minutes` rather than old limit/bonus field names.
- New **Daily gaming time** / **Weekly gaming time** text sensors have explicit `Hh Mm Ss` output. The original numeric duration sensors retain their IDs, minute units and Recorder history, and are now named **Daily gaming time (minutes)** and **Weekly gaming time (minutes)** under diagnostics for graphs and numeric automations. Native HA's `h` duration formatter does not include seconds; this split preserves all three components without corrupting numeric sensor data.
- No game-time history or other integrations are purged; no Windows agent update or automatic enforcement. Home Assistant 0.5.11, Windows agent 0.2.6. Controlled HA deployment and physical Android verification remain separate.

## 0.5.10 — clarify final save action in native application editor

- Name the native **Tracked applications** Options Flow's final button **Save changes** instead of generic **Submit**, using Home Assistant's supported `options.step.tracked_apps.submit` translation. Other steps and the nested Add/Edit dialogs are unchanged.
- Add a short Note that Add, Rename and Delete modify the draft Application List until **Save changes** is pressed. Closing the outer editor without that final action does not persist the edits.
- Retain captured foreground snapshot, process verification, per-PC mapping, safety checks, runtime policy, MQTT and Recorder untouched. This is a HA UI copy-only change. Windows agent remains 0.2.6.
- Regression test reads real Home Assistant Options Flow translations in English and Croatian fallback, with existing editor persistence tests. Standard HA frontend translation cache may need refreshing after deploy.

## 0.5.9 — clearer native Tracked applications snapshot

- The **Currently detected application** section is presented as a Markdown blockquote preview with a level-three heading for the HA-friendly app name (for example **Roblox**), with the safe raw executable and optional vetted Java signature beneath in code formatting. Remove the redundant `Displayed as:` and `Raw sensor value:` prose labels.
- Display **Not tracked** (UI-only) for a fresh foreground executable absent from the HA application list, **Idle** for an explicit idle state, and **Unavailable** for unconfirmed/unknown/ambiguous data. This does **not** change the Active game sensor: its untracked-process value remains `idle`. Escape Markdown punctuation in custom friendly names without modifying the saved name.
- Place a short **Note** after the preview explaining snapshot-only behavior, delayed Add after Alt+Tab/exit, and **X → Configure → Tracked applications** to take a new snapshot. A Markdown divider precedes the existing native **Application List** object editor.
- Blockquote styling (including shading or border) depends on Home Assistant's frontend Markdown renderer; this release does not add a true `ha-card` or custom frontend. Verify the final appearance in the Companion app before claiming a shaded tile.
- HA-only visual update; list Add/Edit/Delete, server-side frozen capture, validation, MQTT transport, budgets, Recorder, entities and Windows agent 0.2.6 are unchanged. Requires 8/8 CI and a separate controlled deployment.

## 0.5.8 — restore readable Configure menu after HA 0.5.7

- Fix the missing labels on the two-option native Options Flow menu. Home Assistant expects `options.step.<step_id>.menu_options` translations for a list of option IDs; the previous `menu` step provided only individual destination step titles. The new menu uses explicit step-ID-to-label pairs as an additional fallback when translation resources are stale.
- Rename the source step translation key from `options.step.menu` to `options.step.settings_menu`. This deliberately avoids an older cached menu description with the retired `Configured actions (in order): {actions}` placeholder. The current source has no such placeholder.
- Keep the same **MQTT configuration** and **Tracked applications** destinations. Do not change device entries, options, app snapshots, budgets, Windows agent behavior, commands or Recorder. HA-only patch version `0.5.8`; Windows remains `0.2.6`.
- On controlled deployment, restart Home Assistant completely, allow integrations to finish starting, then close/reopen Companion. If obsolete text persists, reset the Companion app frontend cache (Settings → Companion App → Reset frontend cache, wording depends on app release) or test in a fresh browser session. Confirm installed integration files/version if the issue still reproduces. Never delete the integration or saved mappings as a cache workaround.
- Regression coverage: menu is a translated two-label dict in the real HA options manager; English and source strings match, and no current menu description requires an unavailable placeholder. This does not prove the post-deploy mobile frontend state; verify with a real device.

## 0.5.7 — freeze foreground enrollment evidence at form entry

- Capture the safe raw v2 identity and separate validated device-scoped enrollment candidate when entering **Configure → Tracked applications** (three-second window), **not** at initial Configure menu entry.
- Keep the candidate solely in the server-side Options Flow instance. **Submit never subscribes to MQTT or rechecks the current foreground process/token.** Parents can complete Add after the child Alt-Tabs, closes the app or takes the PC offline, without time pressure.
- Only captured verified executable/Java identity and previously saved identities are accepted. Never permit arbitrary browser-provided processes, ambiguous bare Java, duplicates or invalid names; keep the race guard for concurrent tracked-app edits. All existing options, entities, controls and recorded game identity remain unchanged.
- Add a prominent snapshot notice in the form: to capture a different application, close (X), reopen Configure, then select Tracked applications. The native HA Options Flow has no reliable Back/Refresh control for this form. An abandoned flow loses the snapshot; no persistent or Windows-side cache.
- Remove the obsolete candidate_changed translation and token-at-submit requirement. Update HA form/editor regression tests, docs and HA-only patch version. Windows agent stays 0.2.6.
- CI and separately coordinated deployment are required; neither merge nor installed version can be assumed from these notes.

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
