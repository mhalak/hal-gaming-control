# MQTT protocol — current Unified v3 monitoring

[← Guides](README.md) · [Operational upgrade](unified_mqtt_telemetry.md)

**The supported Home Assistant monitoring protocol is Unified MQTT v3 only** (HA 0.13.0+, Windows 0.4.0+). Older v2/scalar gameplay and screen topics are not subscribed to, parsed as telemetry, or available as fallback. There is **no protocol configuration switch**.

## Device identity and discovery

The root for a Windows PC is `SmartHouse/Gaming/<device_id>/`. Windows 0.4.0+ derives `device_id` and discovery `name` from the OS computer name; both must match the broker ACLs. A Windows rename changes the MQTT namespace and requires supervised HA re-enrollment. A previously retained old ID is not a second live device.

Retained `discovery` carries `protocol_version: 1` for the **discovery/control metadata format** and explicitly `unified_telemetry_protocol: 3` for **monitoring**. These numbers describe different envelopes; `protocol_version: 1` does **not** imply v1 or v2 gameplay monitoring. HA requires the v3 capability for new enrollment. Retained `availability` reports online/offline and is not proof of fresh foreground evidence.

## Single live monitoring topic

`state/telemetry` contains the complete non-retained JSON version 3 snapshot. MQTT 5 / QoS 0 / six-second expiry / maximum 4096 bytes. Required root keys are `version`, `device_id`, `epoch`, `sequence`, `observed_at`, `foreground`, `display` and `system`. Full exact field names and types are in the [shared, immutable protocol fixture](../tests/contracts/v3/telemetry-foreground.json). Windows source and HA receiver tests validate the same wire example.

Each observation is validated against its own sample age. Epoch/sequence and timestamp reject duplicates, retained replay and old sessions. No telemetry packet can carry a command or grant gaming time. HA derives Active game, exact gaming time, budget indicators and gaming restriction from validated observations and HA-owned settings. Unknown or unavailable data never becomes fabricated idle.

## Separate authenticated control and enrollment channels

- `command/lock_pc` and authorized termination channels carry explicit parent actions, not measurements.
- `state/foreground_candidate` provides a short-lived, non-retained enrollment hint for tracked applications. The editor matches it against the **v3** foreground snapshot before offering Add.
- `state/terminate_offer` and `command/terminate_target` use separate short-lived tokens for a verified, explicitly tracked process; a game quota reaching its limit alone does not initiate a termination.
- `update/status`, signed OTA transport and acknowledgements remain isolated from the monitoring stream.
- Native MQTT discovery continues to expose its existing Uptime entity, with `state_topic` pointed at `state/telemetry` and a bounded `system.uptime_seconds` template.

A control message's own version number may be 1 or 2 without introducing another **monitoring** protocol.

## Upgrading

On HA 0.13.0+ there is nothing to enable under Configure: v3 is mandatory. Old saved per-PC `unified_telemetry_enabled` is removed while retaining settings and Recorder data. If all sensors show Unavailable, verify the stored entry's `device_id`, live Windows hostname topic, capability 3 discovery, MQTT online state and fresh complete v3 packets. Do **not** manually enable old monitoring topics. See the [clean-cut upgrade guide](unified_mqtt_telemetry.md).
