# Unified MQTT v3 — operational protocol and clean-cut upgrade

[← MQTT protocol](mqtt_protocol.md) · [HA integration](ha_integration.md) · [Wire fixture](../tests/contracts/v3/telemetry-foreground.json)

**HA 0.13.0+ and Windows 0.4.0+ use Unified MQTT v3 exclusively.** Neither component offers a switch between monitoring formats. HA drops saved `unified_telemetry_enabled` settings automatically, subscribes only to v3 telemetry, and never reverts to v2.

## Windows publisher

The Windows service derives `device_id` and discovery `name` directly from the OS computer name. It rejects the former configurable `device:` section. It sends all monitoring values in:

`SmartHouse/Gaming/<device_id>/state/telemetry`

Properties: MQTT 5, QoS 0, **retain=false**, message expiry six seconds, maximum 4096-byte complete JSON snapshot. The packet schema is version **3**, with precise field definitions in the [source-controlled shared fixture](../tests/contracts/v3/telemetry-foreground.json). It includes session `epoch`, increasing `sequence`, `observed_at`, verified `foreground` sample and age, `display` state / event evidence / configured timeout, and `system` uptime / agent version. Snapshots are refreshed periodically and on relevant changes. Gaps and reordered/replayed packets are never backfilled.

Retained `discovery` must declare `unified_telemetry_protocol: 3`. MQTT `availability` remains separately published. Signed OTA commands, protected actions, foreground enrollment candidates and verified termination receipts remain separate because they are **not monitoring measurements**.

## HA consumer

HA 0.13.0+ always subscribes to `availability`, `discovery`, and `state/telemetry` for the exact configured device ID. The Tracked applications editor previews the validated v3 foreground only. Direct MQTT Uptime and the native MQTT Uptime entity both derive uptime exclusively from `system.uptime_seconds` in v3. There are no v2 monitoring subscriptions, scalar state topic fallback, or per-PC source controls.

Strict decoding checks exact schema, device identity, non-retention, timestamps, anti-replay session order and independent foreground/display sample freshness. Missing, stale, foreign or malformed data becomes **unknown/unavailable**, not assumed idle or free time. HA owns tracked-app names, budgets, measured totals and bonus journals; it never trusts Windows to enforce a quota. Existing sensor unique IDs and Recorder history are retained for an unchanged MQTT device ID.

## Upgrade checklist

1. Back up HA config/Recorder and the Windows service + configuration. Do not remove Windows security protections to sidestep installer policy.
2. Confirm Windows agent 0.4.0+ is publishing live v3 data under the **actual OS hostname** and that broker ACLs use that exact topic namespace.
3. Update HA to 0.13.0+; no telemetry toggle exists. A stale saved `unified_telemetry_enabled: false` is removed during HA setup. All other options and recorded data remain.
4. **Old HA entries with an older device ID are not automatically retargeted.** Back up their per-PC tracked apps and policy, then explicitly add the new hostname-based device and configure its settings; do not interpret old retained discovery as the currently live PC.
5. Check Active game, daily/weekly budget, daily/weekly gaming time, Gaming restriction, Uptime, reconnect/idle/unknown transitions, and two-PC separation before enabling automated restrictions.
6. If the rollout fails, restore matching known-good HA/Windows backups; there is deliberately no protocol fallback or dual-stream migration.

Source approval, green CI and a successful installation on the actual devices are **separate facts**. Follow [deployment hold #56](https://github.com/mhalak/hal-gaming-control/issues/56) and [regression #201](https://github.com/mhalak/hal-gaming-control/issues/201) before changing household PCs.
