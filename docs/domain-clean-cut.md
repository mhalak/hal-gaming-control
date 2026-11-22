# HA 0.7.0 domain clean cut — one-time installation procedure

**Breaking development preview.** The single supported Home Assistant integration domain is now `hal_gaming_control` in `custom_components/hal_gaming_control`. It replaces all experimental predecessors: `smarthouse_gaming` (0.5.x), `parental` (0.6.0), and `parental_control` (0.6.1, which collided with another project's Marketplace domain). **This is not an in-place upgrade.** No automatic migration, alias, dual installation, or HA registry editing is provided. See [issue #146](https://github.com/mhalak/smarthouse-parental-control/issues/146).

**Windows agent 0.2.6 is unchanged.** Its MQTT root `SmartHouse/Gaming` and `smarthouse_gaming_<device_id>` native MQTT discovery IDs remain the existing wire-protocol contract. Those MQTT identifiers do **not** indicate a second HA custom integration. No Windows agent reinstall is required solely for this HA-domain change.

## Before removing the old integration

1. Identify the correct HA instance and take a **full HA backup/snapshot** (configuration and Recorder included). Record installed versions and the rollback point privately.
2. Make private notes/screenshots of each PC's tracked application names and executable signatures, Daily/Weekly budgets, Weekend bonus, parent bonus, Gaming rules/Unlimited switches, weekday/weekend hours, and any device-specific options. **These options will not be migrated.**
3. Disable relevant HA automations, especially ones that could send **Lock PC** or **Terminate game**. Leave Gaming rules OFF for the initial new installation. Check that no Windows update transaction is active.

## Uninstall first, then install 0.7.0

4. **While the previous integration code still exists**, remove its config entries in **Settings → Devices & services** for each PC. The old entry may be registered under `smarthouse_gaming`, `parental`, or `parental_control`. Confirm there are no old project config entries left.
5. If the old integration was HACS/Marketplace-managed, remove its old installation through that UI where supported. Stop HA and use your supported filesystem/deployment manager to verify that **none** of these old *code* folders remains:
   - `config/custom_components/smarthouse_gaming`
   - `config/custom_components/parental`
   - `config/custom_components/parental_control`
   
   **Never edit HA `.storage` or purge the shared Recorder database** to make this work. Be careful: the `parental_control` directory can belong to a different project, so first identify any installed owner rather than deleting an unrelated package.
6. From the exact **reviewed 0.7.0 source** install **only** `custom_components/hal_gaming_control` (manifest, translations, brand icons and the complete package), either via a verified Marketplace custom-repository download **whose destination is exactly `hal_gaming_control`**, or via the existing controlled, versioned agent/source deployment. **If the UI proposes `parental` or `parental_control`, cancel the download.** Restart Home Assistant.
7. In **Settings → Devices & services → Add integration**, choose **SmartHouse Parental Control**. Enroll the first Windows PC using the existing MQTT/Windows agent, then re-enter tracked applications, limits, bonuses and allowed gaming hours. Keep automatic enforcement disabled. Enroll the second PC after the first passes.

## Smoke test and rollout

8. Verify that each intended PC has exactly one new `hal_gaming_control` config entry, the correct HAL icon and no duplicate project devices; check Active game/Idle/Unavailable, fresh daily and weekly accounting, schedules, additive Weekend bonus and safe manual actions.
9. Review **new entity IDs** and restore HA automations selectively, only after validating their target PC and checking they cannot send unintended commands. Do not enable automatic lock or game termination without explicit parent approval and a real-PC test.
10. Record installed HA 0.7.0 package/commit SHA, actual smoke-test results and rollback evidence. **Source changes and passing CI are not proof of deployment.** Marketplace's *pre-install thumbnail* may require separate catalog/release icon indexing even when the correct icon is bundled in the integration.

## Old history, unknown activity and rollback

Historical Recorder rows under old entity IDs may remain, but **are not migrated or guaranteed to appear under the new entities**. New HA-managed accounting begins with fresh, verified activity; offline/unknown periods must never be charged as observed gaming or interpreted as confirmed idle. Keep the shared Recorder database intact. Re-enter all HA-local settings manually.

If HA cannot remove an old config entry because its package was already deleted, temporarily restore the **matching reviewed legacy code** solely to perform the supported UI removal, then stop HA and switch to the new package. Never edit `.storage/core.config_entries`.

Restoring an HA backup restores the old preview domain and requires repeating this clean-cut process. This is a preview migration, **not a stable 1.0 migration**. Related: #5, #12, #56, #146.
