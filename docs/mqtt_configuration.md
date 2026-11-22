# MQTT connection settings in HAL Gaming Control

The HAL Gaming Control **MQTT configuration** Options Flow step is **read-only**. It reports whether Home Assistant's shared MQTT connection is connected, the configured broker address and port when safely available, the selected PC identity, the device topic root and the current MQTT discovery mode.

**To change Home Assistant's MQTT broker, port, credentials or TLS:**

1. Open Home Assistant **Settings → Devices & services → MQTT**.
2. Choose **Reconfigure** on the existing MQTT integration.
3. Review the impact on all connected devices before confirming shared broker changes.

Official documentation: https://www.home-assistant.io/integrations/mqtt/#broker-configuration

This integration does not initiate its own MQTT connection, store or display credentials, or try to manipulate the MQTT integration's config entry. Unexpected broker values are not echoed as arbitrary text; missing/malformed addresses are reported as unavailable and invalid ports as unknown. Broker status is HA-wide, whereas device identity and MQTT topic root are scoped per PC.

The Windows companion agent uses its **own protected config.yaml** and broker credentials. Reconfiguring HA does not remotely reprovision the agents. Do not copy agent credentials into this public repository or diagnostics.

Since HA 0.5.6, **Configure** exposes only **MQTT configuration** and **Tracked applications**. The MQTT step is informational; it does not need a global Save. Tracked application edits save directly in HA. The former Restrictions and schedule, Windows update settings and Save pages are no longer reachable. Previously stored policy, schedule and updater URL values are **preserved unchanged**; this removal does not disable an already-enabled rule or update entity. Device-page limit controls and manual actions remain available.

## Windows computer name and Home Assistant friendly name

The Windows agent reads the **actual OS computer name** at service startup and uses it as the default discovery label. There is no separate Windows-side display-name setting. The `device_id` is a different concept: it is a persistent random ID stored under protected ProgramData (or preserved from an existing legacy `device.id`) and remains unchanged if Windows is renamed.

Rename the device in **Home Assistant → Settings → Devices & services → Devices** to show any preferred friendly name. HA's user-specified device name (`name_by_user`) takes precedence over the discovered name; do not alter the Windows computer name or the stable MQTT device ID to customize the HA UI. Existing integration config-entry titles may retain their previous label until changed manually. For complete installation and upgrade guidance, see [Windows deployment](windows_deployment.md).
