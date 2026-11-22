# MQTT protocol v1

Root: SmartHouse/Gaming/<device_id>/ (unique ASCII ID). The current Windows agent generates the ID once into protected ProgramData/device_id or keeps an existing legacy config device.id, even when the Windows computer name changes. Discovery name defaults to the current OS computer name; HA owns user-facing aliases and user-defined device names. Provision per-device broker ACLs against this persisted ID, never the hostname. The legacy games catalog remains necessary for the old manual termination path until issue #155 is completed. Retained state/uptime (integer seconds), state/in_game (ON/OFF), state/current_game (idle or sorted unique names joined by " | "), availability (online/offline), and discovery metadata. Game state changes published promptly; full state refresh every 60 seconds.

Retained discovery metadata on discovery: {"protocol_version":1,"device_id":"gaming_pc_01","name":"Gaming PC 1","games":["Minecraft Java","Roblox"],"actions":["terminate_game","lock_pc"]}. This is metadata, not an additional sensor. This example shows baseline metadata. Agent 0.2.x adds foreground capability (`focus_protocol=1`), `agent_version` metadata and two additional foreground entities. Legacy process-presence telemetry remains unchanged.

Commands: command/terminate_game and command/lock_pc accept PRESS, QoS 0, retain false. No acknowledgement protocol. Availability and state changes are not action acknowledgements. No offline quota enforcement.

Broker ACL: per-agent write to own state, availability, discovery and native MQTT discovery config; read only own command topics and HA birth. HA may read these topics and publish fixed commands. MQTT 5 broker required. HA must validate metadata and intersect actions with supported registry.

## Foreground extension (agent 0.2.x)

Retained `state/active_game` reports one configured game name, `idle`, or `unknown`. Retained `state/gaming_active` reports ON/OFF/UNKNOWN. `state/focus_availability` reports online/offline independently of agent availability. Native discovery advertises both foreground entities, gated by agent and focus availability. HA 0.4.3 adds scoped foreground display using the same topics and coherent pair validation. Retained messages alone do not establish freshness; foreground-only accounting, migration boundary and live validation remain pending. The planned 0.5.0 budget changes do not replace process-presence accounting.

## Planned extensions

Application enrollment and remaining-budget popup will require versioned, device-scoped protocol extensions. No topic names or payload schemas are finalized here. HA remains authoritative for quotas and automation decisions; no local automatic enforcement. Do not transmit arbitrary command lines, window titles or browser URLs. See [product direction](product_direction.md).
