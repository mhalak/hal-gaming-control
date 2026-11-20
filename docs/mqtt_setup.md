# MQTT setup and configuration

SmartHouse Parental Control intentionally uses the built-in Home Assistant MQTT integration as its transport. There is one HA broker connection, shared by all enrolled PCs.

## Home Assistant
Open **Settings → Devices & services → MQTT → Configure** to configure or reconfigure the broker address, port, authentication and TLS. The exact dialogs depend on the HA version. Changing this connection can affect other MQTT devices; do not change it merely to add a gaming PC.

In **SmartHouse Parental Control → Configure → MQTT configuration**, view connection status, the shared broker host, port and TLS yes/no, device ID, scoped topics and onboarding mode. If disconnected, use the shown path to check **Settings → Devices & services → MQTT**, then review the Home Assistant log. This screen is informational: it never copies or displays credentials, certificate paths or keys, edits the global MQTT entry, creates another broker client or writes Windows configuration.

Home Assistant and each Windows agent have separate connection configuration. The integration uses HA's existing MQTT integration; each agent uses its protected local `config.yaml`. Changing one does not change the other. If different brokers per PC are needed, that is a separate transport/bridging feature.

In **Configure → Tracked applications**, view the applications reported in the selected PC's discovery data. The list is read-only. Live enrollment, rename and removal are not implemented and remain tracked in issue #7.

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
