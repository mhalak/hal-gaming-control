# MQTT setup and configuration

SmartHouse Parental Control intentionally uses the built-in Home Assistant MQTT integration as its transport. There is one HA broker connection, shared by all enrolled PCs.

## Home Assistant
Open **Settings → Devices & services → MQTT → Configure** to configure or reconfigure the broker address, port, authentication and TLS. The exact dialogs depend on the HA version. Changing this connection can affect other MQTT devices; do not change it merely to add a gaming PC.

In **SmartHouse Parental Control → Configure → MQTT configuration**, view the connection status, the shared broker's host, port and TLS yes/no, the device ID, the topic root and the discovery mode. When the connection is down the screen gives one concrete check (open Settings → Devices & services → MQTT). If the broker details cannot be read safely from the HA MQTT entry (missing, malformed or more than one entry), the screen says "not available" instead of guessing.

This screen is informational and read-only. It never shows, logs or copies the user name, password, certificates or keys, never edits the HA MQTT entry, never creates another broker connection and never writes Windows configuration. It deliberately does not start an MQTT reconfigure flow: HA does support one (`SOURCE_RECONFIGURE` on the MQTT config entry), but a reconfigure flow started from code is hidden from the HA UI, so the user could not complete it, and it would change infrastructure shared with other integrations. Use the path above instead.

There are two separate connections: the shared Home Assistant broker connection (all PCs and other integrations) and each Windows agent's own connection from its protected `config.yaml`. Changing one does not change the other. Central provisioning of the Windows connection is not implemented. If different brokers per PC are needed, that is a separate transport/bridging feature.

In **Configure → Tracked applications**, view the applications currently tracked for the selected PC (read-only, taken from its discovery data). Adding, renaming and removing applications from live detection is part of issue #7 and is not available yet.

## Windows
Copy `windows_agent/config.example.yaml` to a private `config.yaml`, then edit the MQTT section before installation:
```yaml
device:
  id: gaming_pc_01
  name: Gaming PC 1
mqtt:
  host: BROKER_HOST
  port: 1883
  username: gaming_pc_01
  password: REPLACE_WITH_SECRET
  tls: false
  discovery_prefix: homeassistant
```
This illustrates a local test broker; prefer authenticated TLS and the appropriate port/CA configuration for a production broker. Keep each device ID unique and unchanged on upgrade. Store the real configuration in protected ProgramData, not Git. Restart the Windows service after an authorized configuration change. Do not disable Windows security policies.

## Broker permissions
Each agent needs publish access to its own `SmartHouse/Gaming/<device_id>/discovery`, `state/#`, `availability` and (if enabled) `update/status`, and subscribe access to its own fixed `command/#` and the HA birth topic. With native discovery, allow its own fixed discovery config topics and the documented obsolete config cleanup only. HA needs read access to relevant PC telemetry and write access to the intended non-retained command topics. Do not grant a PC access to another PC's commands. Exact ACL syntax is broker-specific. Check the [wire contract](mqtt_protocol.md) for topic names.

## Discovery disabled?
The scoped Add integration flow subscribes to `SmartHouse/Gaming/+/discovery` and lists valid retained metadata. It can create its own raw entities without enabling global MQTT discovery. Do not switch native/scoped modes without a migration plan; history and entity IDs may differ.

## Troubleshooting
Confirm HA MQTT is connected, the service is running, the device publishes its own valid metadata, and uptime advances. Use HA MQTT Listen to a topic on the scoped state/availability topics; never publish test control commands just to check connectivity. Check service.log locally and redact device names, network addresses, credentials and personal paths before sharing.
