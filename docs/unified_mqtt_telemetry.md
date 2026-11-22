# Unified Windows telemetry v3 — issue #176

**Implementation status:** Windows publisher is implemented behind an explicit
**OFF-by-default** compatibility gate. This is **not** an HA cutover, a deployment
or a reason to retire old topics. See [issue #176](https://github.com/mhalak/hal-gaming-control/issues/176)
for the complete authoritative contract and HA acceptance checklist.

## Windows publisher and protocol

Set `telemetry.unified_v3_enabled: true` in the locally protected Windows
`config.yaml` **only for a supervised migration pilot**. This does not alter
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
Existing v2/legacy messages stay unchanged during this compatibility
window, while control channels remain independent: `command/*`, OTA,
`update/status`, one-use terminate offers, `foreground_candidate`,
`availability`, `discovery` and native MQTT discovery are **not
combined** with routine telemetry.

## Coordinated HA migration and rollback

1. Keep the Windows toggle **false** by default. Before piloting, deploy an
   HA decoder that validates the complete v3 envelope and every nested
   subfield, and explicitly negotiates the per-PC capability announced by
   `unified_telemetry_protocol: 3` in retained discovery metadata.
2. In a controlled pilot, enable v3 on **one** Windows PC only. Compare the
   new snapshots with old v2 observations on that PC; verify sample freshness,
   privacy, true active game identity, console ON/OFF, configured timeout,
   AC/DC values, input idle and uptime, with disconnected/locked user,
   gamepad, physical monitor OFF, multi-monitor, reconnect and clock changes.
3. HA must select **exactly one** authoritative foreground/display source per
   PC, preserve existing entity unique IDs and Recorder history, and never
   double-charge time or duplicate Screen Idle bonus. Do not treat publisher
   epoch as an OFF event ID: retain display `event_epoch:event_sequence`.
   A missing v3 feed fails to unknown until an explicit, safe migration
   fallback; do not silently use legacy Windows game names.
4. A failed pilot is rolled back by disabling the Windows toggle and
   explicitly selecting the still-available old HA source. Keep all
   historical accounting/bonus journals intact; do not wildcard-delete
   MQTT discovery or entity registries.
5. Remove old Windows state publishers only **after** HA migration and
   operator approval, in a separate review/PR. This Windows-side change
   does not deploy to family computers, install signed binaries, change
   updater trust, or modify Screen idle / Parent bonus policy.

No HA source or entity implementation is part of this Windows-only PR.
