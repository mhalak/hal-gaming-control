# Unified Windows telemetry v3 — issue #176

**Implementation status:** Windows Preview 20 / agent **0.3.0** uses a **breaking clean cut**: v3 monitoring is mandatory, old retained scalar monitoring states are explicitly cleared, native Uptime discovery reads only the one `state/telemetry` JSON. **No deployment has happened.** This is not an automatic HA migration; HA 0.12.0+ must explicitly select per-PC v3 first. See [issue #176](https://github.com/mhalak/hal-gaming-control/issues/176)
for the complete authoritative contract and HA acceptance checklist.

## Windows publisher and protocol

There is **no** `telemetry.unified_v3_enabled` opt-out in new Windows agent builds. Remove any old disabled `telemetry.unified_v3_enabled: false` key before testing. Use a supervised local migration pilot only. This does not alter
Windows display power settings, enforce any gaming policy or grant a bonus.
When enabled, the Windows service publishes:

- Topic: `SmartHouse/Gaming/<device_id>/state/telemetry`
- MQTT v5, QoS 0, **retain=false**, `MessageExpiryInterval=6` seconds
- Full atomic JSON object, not a partial patch; maximum **4096 bytes**
- At most once per approximately 2 seconds while unchanged; **immediate**
  foreground (including same-executable window switch), display, or power-plan
  transitions. Every refreshed observation has a strictly increasing positive
  int64 `sequence`. Sequence gaps are allowed after dropped QoS0 sends.
- Publisher `epoch`: new random 128-bit lowercase hex per MQTT connection;
  never the display-helper `event_epoch`. Both clocks and the MQTT connection
  must be valid and the pre-existing availability sync complete. Disconnect,
  failed publish, invalid system uptime or clock regression never replay
  an earlier packet. No backfill or retained snapshot.

### Example full snapshot

```json
{
  "version": 3,
  "device_id": "pc_example",
  "epoch": "0123456789abcdef0123456789abcdef",
  "sequence": 19,
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

Values are illustrative. The example intentionally shows an executable
remaining focused while the Windows **logical console** is OFF. It does **not**
prove all monitors are physically off or that Windows turned them off
automatically.

### Source-specific freshness and privacy

`foreground.state` is `foreground | idle | unknown` and is derived only
from the authenticated interactive-user helper's *current verified* sample.
`idle` requires actual fresh helper evidence; a Windows lock, unavailable
helper, invalid process identity or stale sample becomes `unknown` with
null process, signature and sample age. Stable Java class/jar/module
discriminators are validated using the existing strict allowlist rules.

`display.state` is `on | dim | off | unknown`. Its notification
`event_epoch`, `event_sequence` and age refer to an independently
validated Windows `GUID_CONSOLE_DISPLAY_STATE` event. Its
`sample_age_ms` is the age of the authenticated helper observation, not
the time since last MQTT publish; notification age is advanced at packet
capture. On missing, locked, invalid, stale or ambiguous source, all
display event identifiers are null and state is `unknown`. AC/DC
`VIDEOIDLE` seconds, power source and input idle age share the object as
attributes, without extra MQTT topics or HA entities. If a power-plan
read fails, unavailable fields are null/unknown, never invented.

`system.uptime_seconds` is nonnegative Windows `GetTickCount64`
uptime, not a continuous-gaming guarantee. Agent version and build SHA
are from locally validated release metadata. No executable path,
PID, child name, username, full command line, window title, broker
credentials, tokens, grants, policy or private player data is exposed.

A full snapshot is schema v3 only, with no temporary `legacy` section.
Legacy scalar and v2 foreground/display **monitoring messages are no longer published**. The exact previously retained scalar device-state topics are tombstoned on synchronization; old native Uptime `unique_id` is preserved but reads JSON with an expiry. Control channels remain independent: `command/*`, OTA,
`update/status`, one-use terminate offers, `foreground_candidate`,
`availability`, `discovery` and native MQTT discovery are **not
combined** with routine telemetry.

## Coordinated clean-cut HA migration and rollback

1. **BREAKING CHANGE / release hold:** Windows agent 0.3.0 is v3-only for read-only monitoring. HA 0.12.0+ supports v3 but its per-PC `unified_telemetry_enabled` option remains OFF until explicitly switched. Install/configure compatible HA v3 source **before** installing the Windows release. Old HA v2-only accounting will become unavailable (not silently fall back) with the new Windows agent. No legacy dual-publisher compatibility window.
2. Native Uptime retains exactly `smarthouse_gaming_<device_id>_uptime` and exactly the same discovery config topic, but updates the `state_topic` to `state/telemetry`, uses a strictly bounded numeric `value_template`, and expires after 10 seconds. Direct MQTT Uptime already supports the same source while retaining its own unique ID. No duplicate sensor/entity registration.
3. Windows continues to publish `availability`, device `discovery` capabilities, distinct command/OTA and signed update status, and short-lived tracked-app enrollment/targeted termination offers. These are security/control flows, not ordinary telemetry.
4. A supervised Windows SYSTEM + logged-in user / HA pilot must verify exact source compatibility, screen off/on/bonus replay, gamepad and multiple monitors, uptime in native and direct MQTT modes, reconnect, ordering, Recorder, two PCs, target-offer authorization, and rollback. Maintain #56 deployment HOLD until documented acceptance; no signing or binaries are claimed by this source change.
5. **Rollback is coordinated**, not silent: stop/revert the Windows service to a trusted older package **and** explicitly switch HA's per-PC source to v2, then verify without resetting original entity unique IDs, Recorder history or bonus journal. Do not wildcard-delete MQTT or HA registries.

The Windows agent rejects an explicitly disabled legacy `telemetry.unified_v3_enabled: false` configuration and will not start rather than silently publish incompatible monitoring. This is intentionally breaking in development. Old agent-specific retained uptime/activity state topics are tombstoned with QoS 1 acknowledgments on connection. No OTA, command or availability protocol migration occurs in #176.
