# Unified Windows telemetry v3 — Home Assistant consumer (#176)

**Status:** HA source ready for integration tests, **OFF by default**. Preview 19: HA **0.12.0**, Windows agent **0.2.12 unchanged**. Windows v3 publisher, native MQTT Uptime discovery repoint and actual device acceptance are separate work. **Do not deploy/enable on the family PCs** until the common #176 producer/consumer acceptance and [deployment gate #56](https://github.com/mhalak/hal-gaming-control/issues/56) are complete.

## Single read-only MQTT stream

`SmartHouse/Gaming/<device_id>/state/telemetry` — MQTT 5, QoS 0, `retain=false`, six-second message expiry. Every publisher sample is a complete snapshot, approximately every 2 seconds while active and promptly on foreground/display transitions. The producer must use an independent random `epoch` per broker connection and strictly increasing positive `sequence`, with fresh `observed_at`. No replay, backfill or arbitrary online inference.

```json
{
  "version": 3,
  "device_id": "pc_example",
  "epoch": "0123456789abcdef0123456789abcdef",
  "sequence": 123,
  "observed_at": 1790000000.25,
  "foreground": {
    "state": "foreground",
    "process": "RobloxPlayerBeta.exe",
    "signature": null,
    "sample_age_ms": 120
  },
  "display": {
    "state": "off",
    "scope": "windows_console",
    "event_epoch": "fedcba9876543210fedcba9876543210",
    "event_sequence": 37,
    "event_age_ms": 1600,
    "sample_age_ms": 150,
    "ac_timeout_seconds": 600,
    "dc_timeout_seconds": 300,
    "power_source": "ac",
    "last_input_idle_ms": 620000
  },
  "system": {
    "uptime_seconds": 45630,
    "agent_version": "0.2.12",
    "agent_build_sha": null
  }
}
```

The optional bounded five-string `legacy` object is temporary diagnostics only, **never authoritative for time accounting, bonuses or actions**. Production payload must not include user names, IPs, screen titles, process paths, PIDs, credentials or any opaque action tokens.

## HA decoder and accounting invariants

The consumer validates **at most 4096 bytes**, unique JSON keys, exact schema/version/device ID, lowercase 32-character publisher epoch, positive 63-bit sequence, non-retained flag, finite timestamp within 10 seconds (and no more than 2 seconds ahead), and all nested field types/conditional nulls. The existing process-basename and Java public discriminator policy stays authoritative. The per-PC watermark and retired epoch ensure duplicates, retained samples, out-of-order delivery and old-session replay cannot add time.

Windows `foreground` and `display` are *independent authenticated helper observations* inside one atomic publisher snapshot. The field `sample_age_ms` is validated and respected. Stale foreground becomes **unknown**, not idle. Stale screen observations or old display notification receipts become **unknown**, not claimed physical monitor OFF. Display is applied **before** raw foreground accounting. On confirmed OFF, effective game becomes idle without new gaming seconds; when the screen returns ON, a subsequent later fresh foreground packet is needed to resume. The original console `event_epoch:event_sequence` stays intact for replay-safe optional Screen Idle daily bonus. The Windows agent never grants bonuses.

Existing entities and Recorder history are preserved. The **Active game** sensor gets display state, event age, AC/DC timeout, power source, input idle and uptime as attributes. Direct MQTT mode reuses the **same Uptime unique ID** for v3 `system.uptime_seconds` and expires it after missed packets. Native MQTT mode retains its old Uptime discovery identity and requires the **Windows publisher** to change the existing `state_topic` to v3 with a bounded numeric value template when v3 is cut over. Do not publish a second Uptime discovery config.

## Explicit migration and rollback

1. Keep `Unified MQTT telemetry (experimental)` **OFF** on every PC by default. The previous `state/foreground_identity` v2 and optional `state/display_context` v2 remain the only HA accounting sources in this mode. No extra HA entities or history rewrites.
2. Windows independently implements and tests this exact packet format, publishes in parallel with old topics for a **temporary compatibility window**, and advertises capability during retained discovery. Verify the Windows v3 publisher and Uptime discovery repoint on a test PC first. Do not enable HA v3 just because a legacy retained `availability=online` exists.
3. A supervised HA administrator explicitly chooses **Configure → Unified MQTT telemetry (experimental)** and acknowledges the compatibility warning for **one test PC**. HA reloads this per-PC source and subscribes **only** `state/telemetry` for gameplay/display. Old source topics are *not subscribed* for this PC; any absence of v3 is unknown/unavailable, never implicit fallback and never new gaming minutes. Existing tracked app keys, cutover ledger and history are retained.
4. Test two PCs independently, packet loss/reordering/reconnect, missed OFF/ON, activity + Screen Idle bonus idempotence, Java identity, gamepad/multi-monitor caveat, midnight/weekend boundaries, native/direct Uptime and Recorder. Compare v2/v3 without two subscriptions accounting simultaneously.
5. On a mismatch, uncheck v3 per PC **only in a controlled rollback**; the integration reloads v2 and restarts *new* live evidence with the existing ledger. Do not backfill stale periods or force the screen to idle. Legacy publishers/subscribers and exact agent-owned discovery entries may be removed only after real-PC acceptance and final coordinated release.

**Not merged into telemetry:** retained `availability`, `discovery`, HA-owned policies/bonuses, `command/*`, `state/foreground_candidate`, `state/terminate_offer`, `state/terminate_result`, `update/status`, signed OTA chunks and `ota/ack`. These controls and independently authorized receipts remain on their original scoped channels.

**No deploy is implied by green tests**; #56 remains on HOLD until the Windows publisher exists, all current PRs merge, the exact final `main` is green, and signed Windows/backup/real-device safety gates are met.
