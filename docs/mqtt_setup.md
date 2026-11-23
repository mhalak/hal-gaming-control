# MQTT setup and configuration

HAL Gaming Control intentionally uses the built-in Home Assistant MQTT integration as its transport. There is one HA broker connection, shared by all enrolled PCs.

## Home Assistant
Open **Settings → Devices & services → MQTT → Configure** to configure or reconfigure the broker address, port, authentication and TLS. The exact dialogs depend on the HA version. Changing this connection can affect other MQTT devices; do not change it merely to add a gaming PC.

In **HAL Gaming Control → Configure → MQTT configuration**, view connection status, the shared broker host, port and TLS yes/no, device ID, scoped topics and onboarding mode. If disconnected, use the shown path to check **Settings → Devices & services → MQTT**, then review the Home Assistant log. This screen is informational: it never copies or displays credentials, certificate paths or keys, edits the global MQTT entry, creates another broker client or writes Windows configuration.

Home Assistant and each Windows agent have separate connection configuration. The integration uses HA's existing MQTT integration; each agent uses its protected local `config.yaml`. Changing one does not change the other. If different brokers per PC are needed, that is a separate transport/bridging feature.

In **Configure → Tracked applications**, enroll the selected PC's freshly observed foreground application and manage its display name entirely in Home Assistant. No app catalogue or display-name mapping needs to be written to the Windows service. The agent only publishes validated raw process identity, and Home Assistant owns the user-facing name.

## Windows
Copy `windows_agent/config.example.yaml` to a private `config.yaml`, then edit the MQTT section before installation:
```yaml
mqtt:
  host: BROKER_HOST
  username: UNIQUE_ACCOUNT_FOR_THIS_PC
  password: REPLACE_WITH_SECRET
  # Optional: port defaults to 1883, TLS defaults to false.
  # port: 8883
  # tls: true
```
This illustrates a local test broker; use restricted per-device accounts and appropriate TLS. Windows agent **0.4.0+** uses the actual OS computer name for both `device_id` and discovery `name`; it does not use a persisted random ID. Remove any obsolete `device:` block from `config.yaml`, as the new agent rejects it. Its monitoring is only the non-retained `state/telemetry` v3 snapshot. Home Assistant 0.13.0+ consumes only that stream and has no separate telemetry protocol option. Keep local `games` rules optional as documented for manual controls. Store the real config in protected ProgramData, not Git. Restart the service only as part of an authorized upgrade and do not disable Windows security. [Clean-cut guide](unified_mqtt_telemetry.md).

## Broker permissions
Scope broker ACLs to the actual Windows computer name; this is the only device ID in Windows 0.4.0+. Each agent needs publish access to its own `SmartHouse/Gaming/<device_id>/discovery`, `state/#`, `availability` and (if enabled) `update/status`, and subscribe access to its own fixed `command/#` and the HA birth topic. With native discovery, allow its own fixed discovery config topics and the documented obsolete config cleanup only. In the rule-free mode, the agent publishes one additional exact retained empty config on its own old `terminate_game` button topic to retire an obsolete native button; never grant wildcard deletion of other devices. HA needs read access to relevant PC telemetry, including the nonretained, expiring `state/terminate_offer` packets, and write access to the intended non-retained command topics (`command/terminate_target` only for the selected PC). The agent writes non-retained `state/terminate_result` outcomes. Do not permit other gaming PCs or child accounts to publish target commands. Do not grant a PC access to another PC's commands. Exact ACL syntax is broker-specific. Check the [wire contract](mqtt_protocol.md) for topic names.

## Discovery disabled?
The scoped Add integration flow subscribes to `SmartHouse/Gaming/+/discovery` and lists valid retained metadata. It can create its own raw entities without enabling global MQTT discovery. Do not switch native/scoped modes without a migration plan; history and entity IDs may differ.

## Troubleshooting
Confirm HA MQTT is connected, the service is running, the device publishes its own valid metadata, and uptime advances. Use HA MQTT Listen to a topic on the scoped state/availability topics; never publish test control commands just to check connectivity. Check service.log locally and redact device names, network addresses, credentials and personal paths before sharing.
