# MQTT protocol v1

**Cross-component contract tests:** [shared immutable MQTT wire fixtures](../tests/contracts/README.md) are checked by production Windows publisher tests and HA consumer/Options Flow tests. Contract changes require paired regressions and explicit versioning; passing isolated encoder and decoder tests alone is insufficient.
# MQTT protocol v1

**Current Preview 21 / Windows 0.4.0 identity:** `<device_id>` is exactly the validated Windows computer name, not a configurable or persisted ID. All old `device:` YAML overrides are rejected; re-enroll HA and update MQTT ACLs when migrating from earlier installations. This document preserves historical v1/v2 protocol behavior for older versions; current monitoring is v3. See [the migration](windows_deployment.md#agent-040-preview-21--breaking-hostname-only-device-identity).

**Historical v1/v2 behavior only (Windows <= 0.3.0):**

Root: SmartHouse/Gaming/<device_id>/ (unique ASCII ID). Earlier Windows agents generated an ID into protected ProgramData/device_id or retained an existing legacy config device.id even when the Windows computer name changed. Discovery name defaulted to the OS computer name; HA allowed user-facing labels. Provision broker ACLs against the actual selected ID for that version.

Retained discovery metadata on discovery: {"protocol_version":1,"device_id":"gaming_pc_01","name":"Gaming PC 1","games":["Minecraft Java","Roblox"],"actions":["terminate_game","lock_pc"]}. This is metadata, not an additional sensor. This example shows baseline metadata. Agent 0.2.x adds foreground capability (`focus_protocol=1`), `agent_version` metadata and two additional foreground entities. Legacy process-presence telemetry remains unchanged.

Commands: command/lock_pc always accepts PRESS; legacy command/terminate_game accepts PRESS only if local game rules exist. QoS 0, retain false. The new targeted manual command has a separate expiring result event (not a guaranteed synchronous acknowledgement). Availability and state changes are not action acknowledgements. No offline quota enforcement.

Broker ACL: per-agent write to own state, availability, discovery and native MQTT discovery config; read only own command topics and HA birth. HA may read these topics and publish fixed commands. MQTT 5 broker required. HA must validate metadata and intersect actions with supported registry.

## Foreground extension (agent 0.2.x)

Retained `state/active_game` reports one configured game name, `idle`, or `unknown`. Retained `state/gaming_active` reports ON/OFF/UNKNOWN. `state/focus_availability` reports online/offline independently of agent availability. Native discovery advertises both foreground entities, gated by agent and focus availability. HA 0.4.3 adds scoped foreground display using the same topics and coherent pair validation. Retained messages alone do not establish freshness; foreground-only accounting, migration boundary and live validation remain pending. The planned 0.5.0 budget changes do not replace process-presence accounting.

## Planned extensions

Application enrollment and remaining-budget popup will require versioned, device-scoped protocol extensions. No topic names or payload schemas are finalized here. HA remains authoritative for quotas and automation decisions; no local automatic enforcement. Do not transmit arbitrary command lines, window titles or browser URLs. See [product direction](product_direction.md).

## Targeted manual termination v1 (Windows 0.2.9 + HA 0.7.2; issue #155)

On a **rule-free** PC only, the Windows service publishes a one-use token for its last validated foreground process. Home Assistant has the authoritative **Tracked applications** list and shows its **Terminate active game** button only if the offer matches the **same accepted, current raw v2 foreground observation** for an explicitly tracked application. Nothing about a quota breach automatically sends this command.

All three new topics are relative to `SmartHouse/Gaming/<device_id>/`, MQTT 5, **QoS 0, non-retained**, and use a short `MessageExpiryInterval`:

- `state/terminate_offer`: `{"version":1,"device_id":"pc1","epoch":"<32 lowercase hex>","sequence":42,"observed_at":1700000000.0,"process":"RobloxPlayerBeta.exe","signature":null,"token":"<32 lowercase hex>"}`. Valid for less than 4 seconds, tied to a single live foreground snapshot. There is **no PID, process path, session, full argv or username** on the wire. The agent issues a new token on a new valid raw sample and revokes old tokens on focus changes and MQTT reconnect.
- `command/terminate_target`: `{"version":1,"device_id":"pc1","epoch":"<32 lowercase hex>","token":"<32 lowercase hex>","request_id":"<32 lowercase hex>"}`. No arbitrary PID, executable, path, command line, wildcard or user-supplied process selection. A retained, stale, wrong-device/epoch or replayed request is rejected. Broker ACLs must give only the authorized HA/parent account publish access to this exact device's command topic.
- `state/terminate_result`: `{"version":1,"device_id":"pc1","request_id":"<32 lowercase hex>","outcome":"terminated"}` or `"rejected"`. This is a best-effort event, not proof that a game saved its progress; never infer success from the command publish alone.

Before calling Windows `TerminateProcess` on **one** process, the agent requires a *newer* trusted interactive foreground sample and revalidates its private PID, creation timestamp, same unlocked Windows session, name, safe Java entry-point signature (if applicable), process still running and executable not under Windows' system directory or in the protected OS process set. Missing, ambiguous, changed, stale or inaccessible observations fail closed. Background/idle/untracked applications cannot be selected from HA. Generic Java without a safe signature is rejected.

**Compatibility:** If a PC keeps legacy local `games` rules, it keeps the old `command/terminate_game` and native MQTT button and does **not** offer the new targeted action. Without local rules, the old native button is retired; the new **HA-owned** button is present in both native-discovery and scoped/direct modes. An older scoped/direct legacy button may remain visible but unavailable after a rules-free migration. New protocol does not change IDs, budgets, Recorder segments, time tracking or Lock PC. Real user-session acceptance is required before deployment.

**Trust boundary:** An authenticated local broker with per-device topic ACLs is required. These opaque tokens are not cryptographic proof of a trustworthy broker or a defence against a compromised HA/MQTT administrator; do not grant children or untrusted clients control-topic publish access. No cloud relay, command-line execution, browser-title collection or automatic enforcement is added.
