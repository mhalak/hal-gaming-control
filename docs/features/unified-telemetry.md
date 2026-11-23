# Unified MQTT telemetry v3 — the only Home Assistant monitoring protocol

[← Features](../README.md) · [Operational setup](../unified_mqtt_telemetry.md) · [Shared wire contract](../../tests/contracts/v3/telemetry-foreground.json)

**Current source:** HA 0.13.0+ and Windows agent 0.4.0+ communicate with one versioned, device-scoped read-only MQTT stream. The `Unified MQTT telemetry` Configure switch and both legacy v2 monitoring subscriptions have been deleted. There is no fallback or compatibility toggle.

## Topic and envelope

`SmartHouse/Gaming/<Windows-computer-name>/state/telemetry` is published as a **non-retained MQTT 5 QoS 0** packet with six-second message expiry. Full snapshots contain `version: 3`, exact `device_id`, session `epoch`, increasing `sequence`, fresh `observed_at`, and nested `foreground`, `display`, and `system` objects. See the [immutable shared v3 fixture](../../tests/contracts/v3/telemetry-foreground.json) for the exact schema used in Windows publisher and HA consumer tests.

Windows announces `unified_telemetry_protocol: 3` in its retained device `discovery`; HA accepts new devices only with this capability. `availability` stays separate. Commands, MQTT OTA, verified foreground enrollment hints and short-lived termination offers are separate **control** families, not competing monitoring streams.

## Fail-closed safety

HA validates message size, field types, topic/device identity, freshness, non-retained flag, epoch/sequence ordering, foreground process identity, screen events and uptime. Missing or invalid activity is **unknown/unavailable**: it is never counted as idle, gaming, an unauthorized action or a Screen Idle bonus. Confirmed gameplay intervals and existing Recorder history remain HA-owned. Screen Idle bonus remains an **independent feature option**; it does not select the telemetry protocol.

Existing parent-facing HA entities remain the same: Active game, daily/weekly gaming time, daily/weekly remaining budget and Gaming restriction. Display/uptime diagnostics are attributes or existing Uptime entity, not a swarm of new entities.

## Clean-cut upgrade to HA 0.13.0

1. Back up Home Assistant configuration, Recorder data and Windows service configuration. Keep Windows security enabled and test with one PC before enabling enforcement.
2. Run Windows agent **0.4.0+**, which uses its **actual Windows computer name** as the MQTT `device_id`. Verify exact-topic broker ACLs, `discovery` capability 3, `availability=online`, and fresh `state/telemetry` snapshots under that same name.
3. Install HA **0.13.0+**. It automatically removes the obsolete saved `unified_telemetry_enabled` field, leaving budgets, tracked applications, bonuses and historical records unchanged. There is no Configure screen for protocol selection.
4. If the HA entry still points at an older MQTT ID (such as `desktop_lucija`), it cannot receive hostname-scoped packets. **Explicitly re-enroll the current hostname entry** after backing up its settings. Do not delete unrelated HA storage or assume old per-device settings migrate automatically.
5. Verify all six monitoring sensors, two-PC isolation, reconnection, valid idle vs unknown and stable recorded totals on the test PC before production rollout. See [#201](https://github.com/mhalak/hal-gaming-control/issues/201) and [#56](https://github.com/mhalak/hal-gaming-control/issues/56) for acceptance and rollout gates.

**Rollback:** if this upgrade fails, restore a known matching HA+Windows backup. There is no in-product switch to reenable v2 monitoring or to blend data from two sources. Do not reset the Recorder database or fabricate missed usage.
