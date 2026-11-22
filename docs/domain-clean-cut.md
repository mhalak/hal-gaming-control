# HA 0.6.1 domain clean cut — one-time installation procedure

**Breaking preview change.** SmartHouse Parental Control now uses the single
Home Assistant domain `parental_control` and the single package directory
`custom_components/parental_control`. The old `smarthouse_gaming` integration and the briefly used `parental`
0.6.0 domain **cannot be updated in place**, and there is deliberately no automatic
migration, compatibility package, dual installation or hidden registry edit.

Windows agent 0.2.6 and its MQTT topic root `SmartHouse/Gaming` **do not
change**. The old `smarthouse_gaming_<device_id>` **MQTT discovery
identifiers are intentionally retained as wire protocol IDs**. They are not
a second integration.

## Hold: Marketplace domain collision

**Do not perform this 0.6.1 clean-cut installation yet.** The `parental_control` domain in this preview collides with [an unrelated Marketplace integration](https://github.com/cesbron-dev/ha-parental-control) that already uses the same internal domain and has its own brand icon. The Marketplace may display that product's icon on our listing, and it will not allow both packages to coexist. [Tracking issue #146](https://github.com/mhalak/smarthouse-parental-control/issues/146) describes the proposed brand-specific replacement domain and additional clean-cut requirements. The steps below document 0.6.1 historical behavior; follow the updated procedure for the future reviewed unique-domain release rather than installing this conflicting build.

## Before installing 0.6.1

1. Identify the **correct TrueNAS-associated HA instance**. Make a normal
   HA backup/snapshot and record the previously installed build (0.5.x or
   0.6.0) for rollback; do not post local MQTT credentials or device IDs on GitHub.
2. Record each child's device name/ID and relevant **Tracked applications**
   display names and executable signatures, Daily/Weekly budgets, Weekend
   bonus, Parent bonus, Gaming rules/Unlimited switches, weekday/weekend
   windows and other HA-local options. You will need to **configure these
   again**. No old options, history, app mappings or entity IDs are
   guaranteed to migrate. A user can take private screenshots / notes.
3. **Disable any HA automations** depending on the old entities, particularly
   Lock PC and Terminate game. Ensure no Windows agent update transaction
   is pending. Do not run an agent-based hot update over the old installation.

## Clean uninstall and fresh install

4. **While the old HA integration is still present**, navigate to
   Settings → Devices & services → SmartHouse Parental Control and remove
   the **old** config entry for each managed PC using HA's UI (domain
   `smarthouse_gaming`, or `parental` if 0.6.0 was already installed). Confirm the
   old entry is gone. This is a deliberate one-time breaking reset.
5. If installed via HACS, uninstall the old HA integration through HACS
   before reinstalling the renamed domain. Stop Home Assistant and verify
   that both `config/custom_components/smarthouse_gaming` and
   `config/custom_components/parental` are absent. Remove leftover *code files* via the supported filesystem/deployment
   manager; **do not edit any HA `.storage` files** or purge Recorder.
6. Install **only** the reviewed `custom_components/parental_control` directory
   (including manifest, config flow, assets, etc.) in the right HA instance,
   through supported HACS custom-repository installation if available, or
   the existing reviewed source/agent deployment process. Restart HA.
   Do not retain the legacy folder as a sidecar.
7. In HA, Add integration → **SmartHouse Parental Control**; select and
   register the first Windows PC (existing agent and MQTT stay connected).
   Re-enter local Tracked applications, budgets, bonuses and allowed
   weekday/weekend hours; keep **Gaming rules enabled** OFF during smoke
   tests. Repeat for the second PC only once the first passes.
8. Confirm **exactly one** Parental Control entry/device per PC. Test
   fresh Active game / idle / unavailable, current day/week totals,
   schedule, weekend bonus, Windows version and manual actions on a safe
   disposable game; ensure no extra or unsolicited command.
9. Restore selected HA automations only after verifying their **new**
   entity IDs and the correct PC. Keep automatic lock/terminate disabled
   unless the parent explicitly approves a tested automation.
10. Record the installed HA 0.6.1 source commit, build/package SHA,
    successful live checks and rollback evidence. This guide does not
    claim deployment occurred.

## What happens to old history or state?

Removing an integration does not authorize deleting the **shared Recorder
database**. Some historical rows may remain under old entity IDs; they are
not migrated by this change, and new entities may receive different names.
Old HA integration-owned foreground/checkpoint and updater data are not
adopted. New accounts start with unverified fresh activity; never
reinterpret an unknown interval as observed gaming. Budgets and tracked
applications must be re-entered, with **no automatic game enforcement**.

If the old config entry could not be removed because its files were already
deleted, restore the reviewed legacy source **temporarily only to perform
the UI uninstall**, then stop HA and install only `parental_control`. Do not
manually modify `.storage/core.config_entries` or use blanket Recorder
purges. A backup restore returns the previously installed preview domain and must be
followed by this clean installation process again.

This is a **breaking preview release**, not a seamless upgrade and not
a stable 1.0 migration. Related: #5 and deployment #56.
