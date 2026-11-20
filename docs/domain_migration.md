# HA domain migration design and acceptance gate (issue #5)

Status: experimental registry capability tests only. Installed integration remains `smarthouse_gaming` 0.4.2. Do not deploy or advertise a supported domain migration yet.

## Constraints and verified API surface

The hosted runtime environment pins Home Assistant Core 2026.10.2 via pytest-homeassistant-custom-component 0.13.373. Review of that exact Core tag shows that config entry `async_update_entry` does not accept a domain change. Do not mutate the domain or edit .storage files. Core provides entity registry `async_update_entity_platform` for unloaded entities and device registry `async_update_device(new_config_entry_id=...)` for transfer of ownership. The device registry changed recently; do not assume the same API on older HA versions.

Source references:
- https://github.com/home-assistant/core/blob/2026.10.2/homeassistant/config_entries.py
- https://github.com/home-assistant/core/blob/2026.10.2/homeassistant/helpers/entity_registry.py
- https://github.com/home-assistant/core/blob/2026.10.2/homeassistant/helpers/device_registry.py
- https://contributors.home-assistant.io/core/integrations/config-entries/

The first increment exercises these registry APIs on unloaded test entries with synthetic data, including reversal. This does not prove a complete integration migration, Recorder continuity or restart recovery.

## Proposed staged implementation

1. Establish the supported HA API contract in hosted runtime tests, including identity preservation and reversible registry ownership transfer. Cover custom names and disabled entities. Confirm version support before any live use.
2. Add a default-off migration preflight and explicit user initiation. Inventory the old entry, options, entity/device ownership, IDs, registry metadata, native vs scoped MQTT mode, and updater state. Reject duplicate destination IDs, unsupported versions, ambiguous ownership, in-progress update or unsupported configuration; do not mutate anything on failed preflight.
3. Implement an isolated migration transaction with a recoverable journal and an unloaded legacy owner. Create a destination config entry through supported HA entry/flow APIs, transfer only owned entities/device records, and preserve UUIDs, entity IDs, unique IDs, custom settings and native MQTT-owned records. Never run both coordinators for the same device. No automated enforcement throughout migration or rollback. The registry transfer test is not an atomicity guarantee; explicitly validate failure and interruption at each stage. Retire the old entry only after verified destination setup and successful acceptance.
4. Change package folder, manifest, imports, HACS metadata, tests, CI and documentation in a reviewed compatible increment. Preserve the MQTT root SmartHouse/Gaming, device identifier mqtt/smarthouse_gaming_<device_id>, all topic suffixes, discovery IDs and Windows protocol. Do not change accounting or budget semantics in the domain migration.
5. Verify fresh install and upgrade in native and direct MQTT modes, two-device isolation, existing automation/entity references, Recorder history across restart, live options, updater state, reload and rollback. Prove no duplicate subscriptions or commands, and no history gaps incorrectly charged. Establish supported HA versions, backup/restore procedure and rollback instructions before activation.

If the API contract cannot preserve device identity (including composite or MQTT-owned devices) or a safe supported rollback, stop migration rather than deleting entries or recreating users' entities. Entry IDs may necessarily change when creating a replacement entry; inventory dependencies on the original config entry ID and resolve before release. No manual storage-file surgery or private Core APIs as a production mechanism.

The actual rename and migration remain pending. No HA version bump is needed for this test/documentation-only increment.

## Read-only preflight increment

The preliminary helper checks unloaded legacy entry identity, duplicate device identities, destination registry collisions and persisted remote-update state. It is not linked to any runtime or UI path. The updater Store file is inspected read-only on an executor: Core Store.async_load may rename corrupt files or migrate older envelopes. Missing storage is distinct from malformed/unreadable storage; non-null pending data blocks migration. No HA registry .storage files are read or edited. A clean preflight is not migration authorization: device ownership, version support, concurrent changes, durable update-state transfer and transaction recovery remain mandatory.

## Ownership validation increment

Preflight now rejects unknown/multiple owned main devices, child devices, extra identifiers/connections, via-device relationships, subentries, foreign entity platform or device references, and unexpected legacy entity unique-ID prefixes. An independent native MQTT record with the same identifier is not moved. Config entry version/minor version must both be 1. This conservative inventory is specific to the tested HA Core device-ownership model; version compatibility, journal, race prevention and transaction recovery remain pending.
