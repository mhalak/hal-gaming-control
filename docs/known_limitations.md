# What works — and what doesn't yet

[← All guides](README.md) · [← Project home](../README.md)

HAL Gaming Control is still being built. Some things work in testing, but this is **not a finished 1.0 release**.

## Current source behavior

- **HA 0.13.0+ and Windows agent 0.4.0+:** all monitoring uses the single **Unified MQTT v3** snapshot. The HA protocol toggle, legacy scalar activity subscriptions and Recorder fallback were removed. An obsolete saved `unified_telemetry_enabled` flag is discarded without erasing budgets, tracked apps or bonus journals. A hostname change still requires explicit re-enrollment. [Clean-cut instructions](unified_mqtt_telemetry.md).
- **Parent controls and budgets:** HA owns daily/weekly usage, budgets, Parent bonus history/Undo and tracked application names. Live sensor states depend on fresh, correct v3 observations. Missing evidence is `Unavailable`, not free time or confirmed idle.
- **Manual actions:** Lock PC and controlled termination have source support, but safety-sensitive Windows paths require physical acceptance before relying on them.
- **Screen Idle / automatic bonus (HA 0.13.4+):** always active, with no enable/disable option. Verified console OFF suspends new gaming-time charges even if the OFF transition occurred hours earlier, provided fresh ordered display samples continue. Only independently verified eligible pre-OFF idle time can earn a daily bonus. Unknown/unsupported display reporting does not suppress otherwise verified gameplay. A supervised hardware acceptance (gamepads, multiple monitors, manual power-off, reconnects) is still pending.
- **Deployment:** a source merge or HACS release does not prove the Windows service and HA integration are installed or accepted on family PCs.

## What's not ready?

- Trusted signed public Windows installation/update distribution and a supervised physical pilot are still outstanding. Do **not** disable Windows Smart App Control, Defender or other protections.
- Automatic gaming enforcement is not established as safe for household rollout.
- Other platforms and individual browser-tab tracking are not currently supported.

## Good to know

**Playtime can have gaps.** If the PC goes offline, Home Assistant may not know what happened. Missing data is not confirmed idle time.

**Controls aren't tamper-proof.** A Windows administrator may stop the service; locking Windows doesn't necessarily close a game. Terminating a game can lose unsaved progress.

**Keep it private.** Protect your MQTT connection, and don't publish family PC names, private logs or network addresses.

## For developers

Older bugs, signing details and version-specific investigations are in the [archived technical history](reference/known_limitations_history.md), [HA engineering notes](reference/ha_integration_technical.md) and [release history](ha_releases.md).

*Please don't disable Windows security just because a cartoon robot is asking nicely.*

- **Gaming time display:** The friendly `h m s` sensors are text; use the separate numeric minute sensors for graphs or numeric automations.
