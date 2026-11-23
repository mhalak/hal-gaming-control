# Changelog — HAL Gaming Control

[← Project home](../README.md) · [Guides](README.md)

Kids call them new levels. Developers call them releases. Parents call them *“What did you change this time?”*

This is the **human-readable development changelog**. For full technical release notes, see [HA release history](ha_releases.md) and the [Windows deployment guide](windows_deployment.md).

> **Preview software, not a deployment log.** Version numbers below describe changes recorded in source; they do **not** prove that a tagged GitHub Release, a signed Windows installer or an update on any real PC/HA instance exists. Always check the deployed build and the [current compatibility/deployment instructions](known_limitations.md).

**Current source (Preview 27, 23 November 2026):** **Home Assistant 0.13.3** and **Windows agent 0.4.0**. These are **independently versioned**; a newer HA version does not imply a Windows update and vice versa. For the latest declared versions, see the always-updated [`release.json`](../release.json) rather than assuming this dated snapshot is still current.

**🚨 BREAKING CHANGE** means an upgrade can require manual action or break compatibility with prior configs, entity IDs or MQTT payloads. Follow the linked migration instructions before updating; do not assume a normal in-place upgrade is safe.

## Home Assistant integration

### 0.13.3 — Screen OFF accounting reliability (#209, #210)
- Stops accruing gaming time when a fresh OFF report has an invalid display-event receipt; only a verified ON and new foreground sample can resume charging. No unsupported-display false bonus.
- Active game shows the validated display state, with the rejected incoming state shown separately when different. HA-only fix; Windows remains 0.4.0.

### 0.13.2 — Readable MQTT configuration (#207)
- Reorganizes the read-only MQTT configuration information into readable Connection, Broker, Gaming PC and Help sections.

### 0.13.1 — Automatic Screen idle (#204)
- Removes the experimental screen-idle toggle. Verified OFF automatically stops new gaming time; unsupported/unknown display data does not block verified foreground tracking.

### 0.13.0 — BREAKING: Unified MQTT v3 only (#201)
- One mandatory v3 telemetry stream for all PC monitoring; no protocol toggle, v2 subscription or scalar Uptime fallback.
- Stale protocol options are removed without affecting budgets, tracked applications, bonuses or history. Devices are enrolled using the Windows hostname and v3 discovery capability.
- Review the [v3 clean-cut deployment guide](unified_mqtt_telemetry.md) before updating.


### 0.12.0 — Unified MQTT telemetry v3 (Preview 19, #176)
- Adds a strict per-PC v3 JSON telemetry consumer with freshness, device, replay and reconnect checks, plus source-specific display and uptime diagnostics.
- **Historical note:** this was an experimental opt-in in 0.12.0. HA 0.13.0 removes that option and requires v3 on every enrolled PC. [Current setup](unified_mqtt_telemetry.md).

### 0.11.0 — Experimental Screen Idle bonus (#92)
- Adds replay-safe screen display event processing, safer accounting during unverified intervals and an optional daily Screen Idle bonus.
- **Not automatically enabled**; real-PC acceptance testing is still required.

### 0.10.0 — Signed Windows MQTT OTA installation (#166)
- Adds optional advanced settings and guarded HA coordination for approved, signed Windows updates.
- Staging/installation depends on a locally trusted, explicitly provisioned Windows updater. **OFF by default**, not an automatic update mechanism. [Security and setup details](mqtt_ota.md).

### 0.9.0 — Parent bonus history and Undo (#165)
- Each new Parent bonus grant gets a traceable record; the Budget Overview shows active and cancelled grants.
- Admins can select a grant and explicitly prepare/confirm **Undo**. Existing anonymous bonuses are not given invented histories.

### 0.8.0 — Budget Overview (#93)
- Native HA daily/weekly budget receipt with base allowance, Weekend bonus, Parent bonus, time used and remaining time.
- Displays Unlimited gaming and disabled daily quota distinctly; no automatic enforcement change.

### 0.7.2 — Terminate active game (#155)
- Adds a HA-controlled **manual** termination button for a verified, tracked foreground game, guarded by a short-lived device-scoped authorization token.
- Requires compatible Windows 0.2.9 for rule-free PCs; does not terminate arbitrary apps or automate enforcement.

### 0.7.1 — Safer manual controls (#155)
- Legacy **Terminate game** only appears as available when the Windows agent genuinely supports it.
- Windows 0.2.8 rule-free installations keep **Lock PC** without a misleading terminate action.

### 0.7.0 — 🚨 BREAKING CHANGE: new HA domain (#146)
- Renames the integration to **HAL Gaming Control** and adopts only `custom_components/hal_gaming_control` (`hal_gaming_control`).
- **No in-place migration:** remove older project config entries/packages, install the new integration, re-enroll PCs and re-enter HA-local app mappings, budgets, bonuses and schedules. Old entity IDs and Recorder continuity are **not guaranteed**.
- Applies when coming from `smarthouse_gaming` (0.5.x), `parental` (0.6.0) or `parental_control` (0.6.1). **Read the [clean-cut installation guide](domain-clean-cut.md) first.**

### 0.6.1 — 🚨 BREAKING / SUPERSEDED: `parental_control` (#5)
- Temporary, incompatible HA domain rename from `parental` to `parental_control`, still requiring uninstall/re-enrollment.
- **Do not install**: superseded by 0.7.0 after an unrelated integration was found using that domain.

### 0.6.0 — 🚨 BREAKING / SUPERSEDED: `parental` (#5)
- First clean-cut replacement for the former `smarthouse_gaming` domain; **no automatic config or entity migration**.
- **Do not install**: replaced first by 0.6.1, then 0.7.0.

### 0.5.14 — Weekday and weekend gaming schedules (#138)
- Separate allowed-from/until windows for weekdays and weekends.
- Existing weekday settings survive; unconfigured weekends inherit weekday times rather than unexpectedly changing access.

### 0.5.13 — Per-PC gaming schedule (#135)
- Adds native Schedule enabled / Allowed from / Allowed until controls, including overnight intervals and safe defaults.
- Reports schedule-based restriction reasons without automatically locking or closing a game.

### 0.5.12 — Gaming restriction sensor (#3)
- Introduces per-PC **Gaming rules enabled** and a passive Gaming restriction binary sensor with reasons.
- The sensor signals restrictions; it **does not** send enforcement commands by itself.

### 0.5.11 — ⚠️ ENTITY-ID CHANGE: gaming budgets (#116)
- Renames the old limit controls to **Daily budget**, **Weekly budget** and additive **Weekend bonus**, with new number entity IDs.
- **Existing automations referencing old limit entity IDs need review.** Also improves minute-based duration presentation.

### 0.5.10 — Clearer Save changes button
- Labels the last Tracked applications editor action **Save changes** and clarifies when edits actually persist.

### 0.5.9 — Better app detection preview
- Shows clearer, safe raw executable/Java signature details and distinguishes Not tracked, Idle and Unavailable.

### 0.5.8 — Configure menu labels fixed
- Restores readable Options Flow labels and avoids stale translation placeholders.

### 0.5.7 — Stable detected-app enrollment
- Captures trusted foreground evidence when entering the app editor, so switching windows doesn't invalidate a draft immediately.

### 0.5.6 — Simpler Configure flow
- Reduces Configure to MQTT information and Tracked applications editing, with a clearer recent-app snapshot.

### 0.5.5 — Single-page Tracked applications editor
- Consolidates adding, renaming and removing applications into one HA-native form with validation against real detected processes.

### 0.5.4 — Clean-start history option
- Adds narrowly guarded helpers for the owner's deliberate **fresh-history** approach; no blanket Recorder deletion.
- **History note:** manual migration/reset can discard old gaming history. It is **not** automatic; review exact entity IDs before any purge.

### 0.5.3 — Legacy activity entity retirement candidate (#67)
- Consolidates HA-owned Active game/time entities and stops instantiating old direct-MQTT activity entity classes.
- **Compatibility note:** old activity entities require exact-owner, gated cleanup after verified cutover; do not mass-delete registry entries or Recorder data.

### 0.5.2 — HA-owned foreground accounting (#4)
- Introduces per-PC confirmed-only foreground state, application aliases and accounting; rejects unsupported guesses during offline/stale periods.
- Source candidate requiring staged migration validation.

### 0.5.1 — Detect and manage tracked applications (#7)
- Safe Windows foreground candidates, including vetted Java signatures; HA Add/Rename/Remove app mappings.
- Preview candidate, not proof of deployment.

### 0.5.0 — Safety and release groundwork
- Adds HA version diagnostics, read-only MQTT settings, an additive Weekend bonus calculation foundation and removes legacy automatic action-selector execution.
- Preparation for later capabilities; not an announcement that all those features are active.

### 0.4.3 — Scoped foreground telemetry
- Adds scoped Active game/Gaming active reporting, with freshness and device-isolation checks.

### 0.4.2 — Public-preview preparation
- Renames the public-facing integration to SmartHouse Parental Control, adds MQTT configuration info and HACS packaging work.

### 0.4.1 — Limit slider fix
- Restores the disabled/fallback slider positions without changing stored limit semantics.

### 0.4.0 — Windows version diagnostic
- Adds a per-PC sensor showing the Windows agent's reported version.

### 0.3.0 — Parent bonus and native budget controls
- Adds the per-device **Add 30 minutes** action, daily/weekend/weekly controls and live updates.

### 0.2.0 — Unlimited gaming
- Adds a persistent, per-device Unlimited gaming switch and simplifies weekend quota behavior.

### 0.1.0 — First integration
- Initial HA integration and Windows agent protocol used during early development.

## Windows agent

Windows agent version numbers are **separate** from HA versions, even when they share a number.

### 0.4.0 — 🚨 BREAKING CHANGE: Windows hostname is the only device identity (Preview 21, #191)
- The **actual Windows computer name** is now mandatory for *both* the MQTT routing `device_id` and the discovered `name`. The agent reads the OS hostname at runtime: neither value can be overridden by `config.yaml`, and the previously persisted `device_id` file is ignored.
- **Required action:** remove any old `device:` section from the protected Windows `config.yaml` before starting 0.4.0; otherwise the service deliberately fails to start. Prepare the MQTT broker's **per-PC ACL** for the new Windows-hostname topic prefix and keep a backup of the old configuration.
- **🚨 New HA device:** existing prefixes such as `SmartHouse/Gaming/old_pc_id` are **not** automatically renamed to the current hostname. Re-enroll each PC in HA, enable Unified MQTT v3 for the new entry, and review tracked apps, limits, bonuses, schedules and automations. Previous Recorder history is **not** automatically merged. Clear *only* exact obsolete retained MQTT entries after the replacement works; do not wipe shared topics or Recorder history.
- **Windows computer renames change MQTT identity again.** No automatic identity migration, physical rollout, trusted signed package or OTA acceptance is implied. Follow the [supervised hostname migration](windows_deployment.md#agent-040-preview-21--breaking-hostname-only-device-identity) and [MQTT v3 upgrade guide](unified_mqtt_telemetry.md).

### 0.3.0 — 🚨 BREAKING CHANGE: v3-only monitoring (Preview 20, #176)
- Replaces legacy read-only MQTT monitoring state publishers with one scoped **Unified MQTT telemetry v3** JSON packet per PC.
- Safely tombstones old retained agent-owned scalar states; keeps native Uptime discovery identity while sourcing uptime from v3. Commands, availability, OTA and enrollment remain separate.
- **Required action:** install/configure compatible **HA 0.12.0+**, opt in to v3 on each PC, then deploy Windows 0.3.0 under supervision. **Old v2-only HA cannot consume this monitoring stream.** Rollback needs **both** a compatible prior Windows agent and HA source selection. [Upgrade and rollback procedure](unified_mqtt_telemetry.md).
- **Source readiness only:** no physical pilot, signed build or deployed fleet is implied.

### 0.2.12 — Stable updater identity (Preview 18)
- Fixes the separate updater status client to reuse the protected, persistent per-install device ID; validates conflicting/invalid identity configurations.

### 0.2.11 — Signed OTA Install handoff (Preview 17, #166)
- Adds explicit, protected local trust bootstrap for signed MQTT OTA installation.
- **Opt-in and default-off**; the service must not install arbitrary staged archives.

### 0.2.10 — MQTT OTA staging only (Preview 15, #166)
- Adds a gated, **stage-and-ACK only** MQTT package receiver. No installation or execution of staged content.

### 0.2.9 — Verified manual game termination (#155)
- Supports HA-owned one-shot termination offers for exact, verified tracked foreground games on rule-free PCs.

### 0.2.8 — MQTT-only setup (#155)
- New installations can configure the local broker without maintaining a Windows `games` list.
- Legacy Terminate game remains available only on PCs with local rules; Lock PC remains supported.

### 0.2.7 — Automatic PC identity (#155)
- Uses the Windows computer name and stores a stable per-install device ID in protected ProgramData.

### 0.2.6 — Retire old activity discovery (#67)
- Stops advertising old Windows-derived Current game / In game / Gaming active / Active game discovery; HA takes ownership of the user-facing state.
- **Compatibility note:** validate the HA cutover before removing legacy discovery data.

### 0.2.5 — Foreground identity v2
- Adds non-retained, privacy-limited per-PC foreground identity telemetry independent of local game rules.

### 0.2.4 — Safe app candidate transport
- Introduces bounded executable/Java identity and expiring enrollment candidates to support HA-managed tracked apps.

### 0.2.3 — Release provenance preparation
- Allocated alongside HA 0.5.0 for reviewed Windows packaging and source-build identification.

Older experimental Windows agent versions share the [early HA/agent history](ha_releases.md); the repository does not provide a verified independent release log for each early Windows patch.

---

**Still unsure what version is safe?** The changelog tells you what changed; the [known limitations](known_limitations.md), [Windows deployment guide](windows_deployment.md) and [HA clean-cut instructions](domain-clean-cut.md) tell you what you must verify before installing.

*The only thing with more revisions than the code is the phrase “just five more minutes.”*
