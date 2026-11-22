# Integration domain migration — issue #5 (research / staging)

## Status

**Blocked for production cutover.** No domain rename, .storage edits or
live registry mutations have been implemented or authorized by this document.

The HA integration currently uses domain `smarthouse_gaming` and user-facing
name **SmartHouse Parental Control**. The proposed new internal domain is
`parental`. The MQTT wire root remains `SmartHouse/Gaming`: the Windows
agent must not be reconfigured just because HA's internal package changes.

### Confirmed Home Assistant API limitation

Home Assistant's `ConfigEntry` stores `domain` and `entry_id` as frozen
attributes (see [Core source](https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py)).
`hass.config_entries.async_update_entry()` can update `data`,
`options`, `unique_id` and other allowed fields, **not the domain**.
`async_migrate_entry()` is for schema/version changes **within one domain**;
it does not reassign a pre-existing config entry to `parental`.

Consequently, renaming the custom-components directory and manifest alone
would leave installed `smarthouse_gaming` config entries behind. Adding
`parental` independently may create a second config entry, extra entity
IDs (often suffixed `_2`), split stored settings, duplicated MQTT listeners
or command exposure. **Do not deploy a naive package rename.**

There is an existing Core-only special mapping for blocked custom integrations
replaced by built-in integrations. That does **not** establish a supported
general-purpose mapping for arbitrary third-party domain changes.

## Public registry migration APIs verified for HA 2026.10.2

The initial research blocker was **config entry domain immutability**, not the
availability of all cross-domain migration APIs. HA Core **does** expose:

- `entity_registry.async_update_entity_platform(entity_id, "parental",
  new_config_entry_id=target.entry_id)` — explicitly intended for moving
  **unloaded** entities between integrations. Retains `entity_id`,
  registry `id`, original `unique_id` and user edits when allowed.
- `device_registry.async_update_device(device_id,
  new_config_entry_id=target.entry_id)` — moves device ownership without
  changing its registry `id` or MQTT identifiers.

See
[entity registry in HA 2026.10.2](https://github.com/home-assistant/core/blob/2026.10.2/homeassistant/helpers/entity_registry.py)
and
[device registry in HA 2026.10.2](https://github.com/home-assistant/core/blob/2026.10.2/homeassistant/helpers/device_registry.py).

`tests/home_assistant/test_domain_registry_transfer.py` exercises these
public methods against real in-memory HA registries, including keeping the
same IDs, custom names and icons, reverse transfer before source deletion,
native MQTT-owned separation, and cleanup of a transferred source entry.

**Important:** these tests prove registry operations, **not a complete
crash-safe domain migration**. A new-domain config entry still needs to be
created using its config flow, the old package must be retained temporarily
to unload/remove its old entry, and all integration-owned per-entry Stores
(foreground intervals, updater state, etc.) must be transferred or keyed
safely. If the power fails between registry operations, the existing
journal must reconcile and roll back partial moves on startup. Do not
deploy until this is fully tested.

## Already available safeguards

- `migration_preflight.async_preflight` inspects an **unloaded** source
  config entry; blocks invalid identity/version, duplicates, unrelated
  registry ownership and pending/corrupt updater transactions.
- `domain_migration_inventory.async_inventory` copies exact config
  `data`, `options`, owned entity/device registry IDs and updater store key
  **only in memory** after a successful preflight. It performs no mutation,
  export, logging or network communication. Its data may be sensitive.
- `migration_journal.MigrationJournal` durably records planned stages and
  rejects conflicting/invalid transitions; it does not transfer ownership.

An empty preflight result or a built inventory is **not** permission to
perform a migration. A supported cross-domain transfer and transactional
recovery must first be implemented and verified.

## Required implementation/acceptance before production activation

1. Identify the TrueNAS-associated test HA and take a verified backup of
   configuration, all Parental Control entry options and app mappings,
   entity/device registries, Recorder and integration-owned updater state.
   Keep local IDs/secrets out of public issue comments.
2. Prove on the same supported HA version that a new `parental` entry
   can be created using public config-flow APIs with exact preserved
   data/options. Verify no old and new entry can run simultaneously and
   no duplicate MQTT subscriptions or remote commands occur.
3. Build an **atomic orchestration** around the verified public entity/device
   transfer APIs; validate exact pre-/post-conditions, run a one-PC pilot,
   verify historical Recorder continuity and leave native MQTT-owned entities
   untouched. If any metadata/history cannot be preserved, stop and obtain
   explicit owner approval before a preview reset.
4. Verify integration-owned Recorder/foreground checkpoint and
   updater stores remain accessible under the new entry identity.
   In particular, an update transaction must never be pending during
   migration; no resumed update command may be replayed.
5. Exercise a durable staged journal across simulated crash points:
   prepare, unload/stop old source, target creation, registry transfer,
   verification, commit and rollback to the old installation on failure.
   Fail closed on data mismatches, unsupported versions and collisions.
   No raw edits of HA `.storage`.
6. RED→GREEN tests on fresh install, old entry upgrade, both MQTT modes,
   two PCs, restart/reload, outage/rollback and mixed old agents; pass
   all CI/coverage/complexity gates. Pilot **one** authorized PC before
   touching the second.

Until these criteria are proven, keep `smarthouse_gaming` running. The
display name already says Parental Control, so deferring an internal domain
rename does not reduce day-to-day functionality.

Related: #5 migration, #6 device-scoped actions, #56 agent-based deployment.
