> **Archived engineering notes (21 November 2026).** These notes cover specific development versions and may be outdated. For the shorter parent-facing guide, [start here](../ha_integration.md).

---

# Home Assistant integration

[← Documentation hub](../README.md) · [← Project home](../../README.md)

**Looking for step-by-step instructions rather than the version-specific reference?** Start with [Track applications](../features/tracked-applications.md), [Gaming budgets and bonuses](../features/gaming-budgets.md), and [Manual parent actions](../features/parent-actions.md). The [Screen idle bonus](../features/screen-idle-bonus.md) and [Budget overview](../features/budget-overview.md) are documented plans, **not shipped controls**.

## Version status

**0.5.0 is a deployment candidate, not a verified installation.** It includes removal of implicit actions/selectors, safe MQTT configuration diagnostics, local version diagnostics, and the opt-in weekend bonus calculation kernel. The expanded feature set described below (duration sensors, full Weekend bonus UI, fresh restriction sensor) is still planned and **not included** in this 0.5.0 build. Existing installations retain the legacy Weekend daily limit UI until a separate safe migration. See [release history](../ha_releases.md) and [product direction](../product_direction.md).

In current HA 0.5.10, Configure contains only **MQTT configuration** (read-only) and **Tracked applications** (saves on **Save changes**). The older Restrictions and schedule, Windows update settings and Save steps were removed without changing existing stored policy, schedule, catalog URL or legacy action options; existing enabled controls still operate according to their saved values. Limit sliders and manual device controls remain on the device page.

The application editor now shows the latest fresh v2 raw foreground process identity (executable basename and vetted Java signature only) and its HA-normalized display label above the Application List. A mapped foreground app shows its saved name, an untracked executable displays `idle` for tracked gameplay, and unavailable/ambiguous observations are not mislabeled as idle. The standard Home Assistant Options Flow is a snapshot at form entry: it **cannot live-update an open form** while focus changes, so close and reopen Tracked applications after switching apps on the PC. The Add selector comes from a separately validated, fresh foreground candidate **captured only when entering Tracked applications**, not at the initial Configure menu. That validated process and safe Java discriminator stay server-side on the active Options Flow instance until **Save changes** or abandonment. Saving does **not** poll MQTT, compare the latest token or require the child to remain in the application; parents may finish editing after Alt+Tab, game exit or PC disconnection. A new detection requires closing the dialog (X) and reopening **Configure → Tracked applications**. Native forms do not provide a reliable one-step Back or Refresh control. Reject browser-invented identities and concurrent edits to this device's tracked apps as before. No raw argv, PID, window titles or private executable paths are sent to the frontend or saved in HA app mappings.

HA 0.5.8 also fixes missing Configure menu labels caused by omitted `menu_options` translations in 0.5.7. The menu now provides readable labels even if translations are missing. Its new `settings_menu` step key avoids the retired cached `{actions}` description. After installation, perform a **full HA restart**, then reopen Companion (or reset only its frontend cache) if stale text remains. Do not delete any config entry or options to fix display-only translation problems.

**Native Save changes label in HA 0.5.10:** In the Tracked applications form, inner Add/Edit and Delete only update the proposed on-screen list. Press the outer **Save changes** button to persist additions, renames and removals. Closing the form without pressing it discards pending edits. The underlying ObjectSelector has not been converted to autosave; instant per-row saving and Android keyboard Enter remain deferred to the custom frontend backlog #89.

**Visual-only editor refresh in HA 0.5.9:** The Currently detected application preview emphasizes the tracked HA name above its safe raw executable within a Markdown blockquote. An unregistered foreground executable is labeled `Not tracked` **only in the editor**, while the Active game sensor continues to report `idle` for untracked apps; explicit `Idle` and `Unavailable` are distinct states. A short Note separates the preview from the Application List. Frontend blockquote appearance is theme/renderer-dependent (background and border are not guaranteed); no custom frontend was added. Existing app mapping persistence, snapshot timing and the requirement to close/reopen the editor to recapture remain unchanged.

Install custom_components/smarthouse_gaming through manual installation or HACS where available. Restart HA. MQTT and Recorder must be enabled. Add one config entry per PC using scoped or native MQTT discovery. Restrictions are disabled by default.

## Planned device controls — after the 0.5.0 preview

Daily gaming time and Weekly gaming time show the Recorder-accounted minutes (local day and Monday-based week). They are independent of enabled restrictions, unlimited mode and quota settings; missing accounting data is unavailable. Unobserved intervals are not charged (see recorder_coverage.md). Current accounting uses process presence, not foreground activity. Recorder must include current_game and uptime; retain at least seven days of history. Offline/unobserved intervals are bounded by heartbeat coverage; missing history is not reconstructed.

Daily limit and Weekly limit are independently enforced, with slider values 0–600 minutes and -10 mapping to the disabled -1 sentinel. Weekend bonus is 0–600 minutes, step 10, added separately on Saturday and Sunday each time. Add 30 minutes adds a date-scoped cumulative daily bonus, expiring at local midnight. Neither bonus changes the weekly limit. Example: daily 60 min + weekend bonus 120 min = 180 min on Saturday and 180 min on Sunday, each subject to the weekly cap. A disabled daily limit stays unlimited; zero allows only applicable bonuses. Unlimited gaming bypasses policy without clearing usage.

Daily budget and Weekly budget retain remaining percentages and minute attributes. The legacy schedule/restriction-enable values remain stored but are no longer edited in Configure (equal schedule start/end means all day). The MQTT configuration screen explains the shared connection and separate Windows agent connection; Tracked applications shows device-scoped Windows foreground candidates and offers HA-only alias Add/Rename/Remove; stored aliases do not yet drive Active game until #4 cutover. Manual Terminate game and Lock PC buttons retain their existing command topics and do not require enabled policy.

## Automation-only command execution — 0.5.0 preview (restriction trigger pending)

No game command is automatically published by the integration. Turn on restrictions only after validating the reported gaming behavior. Use the per-PC Gaming restriction active binary sensor as an automation trigger: ON means the current coherent active game has a rule violation while fresh uptime coverage is available. Reasons are machine-readable attributes (daily, weekly, schedule, game:<name>). OFF means no active violation; unavailable means the PC/source is not confirmed live. The gate requires a changed uptime observation after reconnect or startup; a stale retained state is not sufficient. State refresh is periodic and on telemetry or configuration changes.

For example, in HA create an automation triggered when the restriction sensor becomes ON. Notify, optionally delay, then check it is still ON before pressing the existing Terminate game button. Use a periodic trigger with the same confirmation if repeated action is desired; do not assume a state trigger fires again while continuously ON, including across a restart. Test with disposable game sessions. No automation is installed automatically.

## Future UI migration from 0.4.x (not yet implemented)

Back up integration and config entry options before deployment. Retire any legacy action selections; recreate desired behavior as a native automation before relying on restrictions. Legacy weekend override -1 becomes bonus 0; otherwise a finite daily limit with weekend override greater than or equal to daily converts to their difference. A lower weekend limit or a finite weekend override with unlimited daily requires an explicit owner policy decision before deployment. The integration refuses incompatible migration rather than silently loosening the quota. Existing values requiring a negative bonus, values above 600 minutes, or a bonus not divisible by 10 cannot be represented exactly and require an explicit owner decision; no approximate or silent adjustment is allowed. The migration preview does not change persisted options. Existing daily/weekly entity identities and source history must be preserved as part of a separately tested migration; the legacy weekend number control cannot be retired before its safe replacement is available.

Verify both devices, minute sensor consistency, policy/bonus boundaries, manual commands, automation triggers, offline and reconnect behavior. Do not change existing automation or enable restrictions without owner approval.

Windows update settings are separate; remote updates remain disabled unless provisioned and verified.

## Planned follow-ups

The foreground follow-up migrates accounting to foreground-only telemetry in both MQTT modes. Application enrollment adds Application list under the integration's Configure menu, including enrollment from live foreground identity. The planned Windows helper adds the remaining-time warning popup. These are not available as 0.5.0 features. See [product direction](../product_direction.md).

## Legacy 0.4.2 reference

The legacy weekend daily override is not additive: -10 on the slider (stored -1) falls back to the daily allowance on weekends. Older deployments may still expose legacy Add/Remove/Move action controls and internal enforcement. In source revisions containing the action-cleanup PR, those controls and the implicit execution path are removed; existing options remain for rollback. Keep restrictions disabled during testing and avoid duplicate enforcement by external automation. Manual buttons and agent version reporting are already present. Daily and weekly budget sensors show remaining percentages and used_minutes attributes. Do not retrospectively interpret historical process-presence data as foreground play.

## Incremental weekend bonus kernel (pre-UI)

When and only when the config contains an explicit valid `weekend_bonus` key (integer 0–600, step 10), the daily allowance is `daily + weekend_bonus` on local Saturday and Sunday, plus any date-scoped one-off bonus. A `daily` value of -1 remains unlimited; weekly allowance stays independent. Without the new key, legacy `weekend_daily` behavior remains unchanged. `preview_weekend_bonus_migration()` computes an exactly equivalent candidate bonus or reports that manual resolution is needed; it never writes config. This incremental helper is not an owner-facing setting, automatic migration or authorization to deploy a new policy.
