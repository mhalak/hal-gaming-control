# Unified Windows telemetry v3 — Home Assistant consumer (#176)

**Current HA source:** Preview 19 / HA **0.12.0** is merged, with the post-ON follow-up #184 also on `main`. **Windows next source candidate:** Preview 20 / agent **0.3.0** is being implemented separately as a **breaking clean cut**; its native Uptime discovery repoint is part of that Windows branch, not yet merged/installed. New Windows 0.3.0 has **no v2/v3 publisher switch**: it publishes only unified v3 monitoring and tombstones its old retained scalar monitoring fields. **Do not deploy/enable on the family PCs** until the common #176 producer/consumer acceptance and [deployment gate #56](https://github.com/mhalak/hal-gaming-control/issues/56) are complete.

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

Existing entities and Recorder history are preserved. The **Active game** sensor gets display state, event age, AC/DC timeout, power source, input idle and uptime as attributes. Direct MQTT mode reuses the **same Uptime unique ID** for v3 `system.uptime_seconds` and expires it after missed packets. Native MQTT Uptime keeps the **same discovery topic, unique ID and entity**. The incoming Windows 0.3.0 clean-cut agent repoints its existing Uptime discovery `state_topic` to `state/telemetry` with a bounded numeric template and message-staleness expiry. It does not create a second Uptime entity. Old retained scalar MQTT monitoring values are cleared for this PC.

## Coordinated clean cut and rollback

1. **Do not deploy yet.** HA v3 is opt-in per device, OFF by default, and Windows 0.3.0 will be **v3-only** for read-only monitoring. The Windows agent no longer offers `telemetry.unified_v3_enabled` or a compatibility window that publishes old scalar/foreground/display topics in parallel. Commands, OTA and separately authenticated control/receipt topics remain independent.
2. During an approved **single-PC maintenance window**, back up HA configuration/Recorder and Windows service/ProgramData, verify exact release SHA and signed Windows build, and confirm the PC's durable device ID. Stage HA **before** updating the Windows service. An administrator can select **Configure → Unified MQTT telemetry (experimental)** for exactly that PC and acknowledge the warning. Until Windows 0.3.0 starts advertising `unified_telemetry_protocol: 3` and live `state/telemetry` packets, gameplay/Screen Idle are **UNKNOWN**; HA does **not** fall back to the old v2 sources or invent usage. This temporary loss of live observations must be planned, not hidden.
3. Install the **trusted Windows 0.3.0** package only after its own signing/bootstrap/Smart App Control gates pass. The clean-cut publisher must replace old read-only monitoring (including native Uptime), tombstone **only the exact agent-owned old retained scalar states**, preserve existing `homeassistant/sensor/..._uptime/config` identity and use `state/telemetry` with a bounded numeric value template and expiry. Confirm retained discovery `unified_telemetry_protocol: 3`, a fresh non-retained session epoch and correctly ordered snapshots. Do not treat retained discovery or availability as proof of current live gameplay.
4. Verify account reconciliation on one test PC: every game/idle/unknown boundary, safe Minecraft/Java discriminator, Screen Idle ON/OFF freshness and bonus idempotence, packet losses, broker restart/epoch renewal, two-PC isolation, original Uptime entity ID in both direct/native modes, Recorder totals, midnight/DST and rollback. Keep controls and OTA topics isolated; never disable Windows security to make a build pass.
5. **Rollback is a paired operation.** Windows 0.3.0 has no v2 monitoring publisher, so simply switching HA's v3 option OFF would leave gameplay unknown. If acceptance fails, restore the previously trusted Windows package **and** the corresponding HA v2 setting/compatible integration as one supervised rollback. Do not restore retained old gameplay samples, force stale OFF to idle, or backfill unobserved time. Preserve historical HA entity unique IDs and durable usage records.

The compatibility cutover is not an excuse to publish two authoritative monitoring streams. Each target PC has exactly one HA accounting source; all migration, physical acceptance and any eventual release remain blocked by #56.

**Not merged into telemetry:** retained `availability`, `discovery`, HA-owned policies/bonuses, `command/*`, `state/foreground_candidate`, `state/terminate_offer`, `state/terminate_result`, `update/status`, signed OTA chunks and `ota/ack`. These controls and independently authorized receipts remain on their original scoped channels.

**No deploy is implied by green tests**; #56 remains on HOLD until the clean-cut Windows 0.3.0 branch merges, the exact final `main` is green, and signed Windows/backup/real-device safety gates are met.
