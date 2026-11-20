# Home Assistant integration

## Version status

**0.5.0 is a deployment candidate, not a verified installation.** It includes removal of implicit actions/selectors, safe MQTT configuration diagnostics, local version diagnostics, and the opt-in weekend bonus calculation kernel. The expanded feature set described below (duration sensors, full Weekend bonus UI, fresh restriction sensor) is still planned and **not included** in this 0.5.0 build. Existing installations retain the legacy Weekend daily limit UI until a separate safe migration. See [release history](ha_releases.md) and [product direction](product_direction.md).

Install custom_components/smarthouse_gaming through manual installation or HACS where available. Restart HA. MQTT and Recorder must be enabled. Add one config entry per PC using scoped or native MQTT discovery. Restrictions are disabled by default.

## Planned device controls — after the 0.5.0 preview

Daily gaming time and Weekly gaming time show the Recorder-accounted minutes (local day and Monday-based week). They are independent of enabled restrictions, unlimited mode and quota settings; missing accounting data is unavailable. Unobserved intervals are not charged (see recorder_coverage.md). Current accounting uses process presence, not foreground activity. Recorder must include current_game and uptime; retain at least seven days of history. Offline/unobserved intervals are bounded by heartbeat coverage; missing history is not reconstructed.

Daily limit and Weekly limit are independently enforced, with slider values 0–600 minutes and -10 mapping to the disabled -1 sentinel. Weekend bonus is 0–600 minutes, step 10, added separately on Saturday and Sunday each time. Add 30 minutes adds a date-scoped cumulative daily bonus, expiring at local midnight. Neither bonus changes the weekly limit. Example: daily 60 min + weekend bonus 120 min = 180 min on Saturday and 180 min on Sunday, each subject to the weekly cap. A disabled daily limit stays unlimited; zero allows only applicable bonuses. Unlimited gaming bypasses policy without clearing usage.

Daily budget and Weekly budget retain remaining percentages and minute attributes. Configure enables policy evaluation and sets schedule (equal start/end means all day). The MQTT configuration screen explains the shared connection and separate Windows agent connection; Tracked applications lists each configured PC's reported applications read-only. Manual Terminate game and Lock PC buttons retain their existing command topics and do not require enabled policy.

## Automation-only command execution — 0.5.0 preview (restriction trigger pending)

No game command is automatically published by the integration. Turn on restrictions only after validating the reported gaming behavior. Use the per-PC Gaming restriction active binary sensor as an automation trigger: ON means the current coherent active game has a rule violation while fresh uptime coverage is available. Reasons are machine-readable attributes (daily, weekly, schedule, game:<name>). OFF means no active violation; unavailable means the PC/source is not confirmed live. The gate requires a changed uptime observation after reconnect or startup; a stale retained state is not sufficient. State refresh is periodic and on telemetry or configuration changes.

For example, in HA create an automation triggered when the restriction sensor becomes ON. Notify, optionally delay, then check it is still ON before pressing the existing Terminate game button. Use a periodic trigger with the same confirmation if repeated action is desired; do not assume a state trigger fires again while continuously ON, including across a restart. Test with disposable game sessions. No automation is installed automatically.

## Future UI migration from 0.4.x (not yet implemented)

Back up integration and config entry options before deployment. Retire any legacy action selections; recreate desired behavior as a native automation before relying on restrictions. Legacy weekend override -1 becomes bonus 0; otherwise a finite daily limit with weekend override greater than or equal to daily converts to their difference. A lower weekend limit or a finite weekend override with unlimited daily requires an explicit owner policy decision before deployment. The integration refuses incompatible migration rather than silently loosening the quota. Existing values requiring a negative bonus, values above 600 minutes, or a bonus not divisible by 10 cannot be represented exactly and require an explicit owner decision; no approximate or silent adjustment is allowed. The migration preview does not change persisted options. Existing daily/weekly entity identities and source history must be preserved as part of a separately tested migration; the legacy weekend number control cannot be retired before its safe replacement is available.

Verify both devices, minute sensor consistency, policy/bonus boundaries, manual commands, automation triggers, offline and reconnect behavior. Do not change existing automation or enable restrictions without owner approval.

Windows update settings are separate; remote updates remain disabled unless provisioned and verified.

## Planned follow-ups

The foreground follow-up migrates accounting to foreground-only telemetry in both MQTT modes. Application enrollment adds Application list under the integration's Configure menu, including enrollment from live foreground identity. The planned Windows helper adds the remaining-time warning popup. These are not available as 0.5.0 features. See [product direction](product_direction.md).

## Legacy 0.4.2 reference

The legacy weekend daily override is not additive: -10 on the slider (stored -1) falls back to the daily allowance on weekends. Older deployments may still expose legacy Add/Remove/Move action controls and internal enforcement. In source revisions containing the action-cleanup PR, those controls and the implicit execution path are removed; existing options remain for rollback. Keep restrictions disabled during testing and avoid duplicate enforcement by external automation. Manual buttons and agent version reporting are already present. Daily and weekly budget sensors show remaining percentages and used_minutes attributes. Do not retrospectively interpret historical process-presence data as foreground play.

## Incremental weekend bonus kernel (pre-UI)

When and only when the config contains an explicit valid `weekend_bonus` key (integer 0–600, step 10), the daily allowance is `daily + weekend_bonus` on local Saturday and Sunday, plus any date-scoped one-off bonus. A `daily` value of -1 remains unlimited; weekly allowance stays independent. Without the new key, legacy `weekend_daily` behavior remains unchanged. `preview_weekend_bonus_migration()` computes an exactly equivalent candidate bonus or reports that manual resolution is needed; it never writes config. This incremental helper is not an owner-facing setting, automatic migration or authorization to deploy a new policy.
