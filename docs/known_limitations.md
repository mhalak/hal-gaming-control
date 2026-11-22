# What works — and what doesn't yet

[← All guides](README.md) · [← Project home](../README.md)

SmartHouse Parental Control is still being built. Some things work in testing, but this is **not a finished 1.0 release**.

## What can I try?

- **Lock PC** and **Terminate game** worked in limited real-PC tests. They still need testing on your own devices.
- **Daily and weekly budgets**, **Weekend bonus**, **Add 30 minutes** and the **Tracked applications** editor exist in preview source. What you see depends on your installed version.
- Windows reports app activity to Home Assistant, but **full foreground-only tracking still needs end-to-end testing**.

Our robot is enthusiastic. We're a little more careful.

## What's not ready?

- **Automatic game closing or locking** is not validated or enabled by default.
- **AFK bonuses** and the itemized **Budget Overview** are **planned**, not working features.
- **Windows installation:** There is no verified signed public installer. Windows Smart App Control has blocked an unsigned build. **Don't turn off Smart App Control, Defender or other protections** to make it run.
- **Updates:** The trusted Windows updater and stable release are still being tested.
- **Platforms:** The Windows companion targets **64-bit Windows 10/11**. Other systems and individual browser-tab tracking aren't supported.

## Good to know

**Playtime can have gaps.** If the PC goes offline, Home Assistant may not know what happened. Missing data is not confirmed idle time.

**Controls aren't tamper-proof.** A Windows administrator may stop the service; locking Windows doesn't necessarily close a game. Terminating a game can lose unsaved progress.

**Keep it private.** Protect your MQTT connection, and don't publish family PC names, private logs or network addresses.

## For developers

Older bugs, signing details and version-specific investigations are in the [archived technical history](reference/known_limitations_history.md), [HA engineering notes](reference/ha_integration_technical.md) and [release history](ha_releases.md).

*Please don't disable Windows security just because a cartoon robot is asking nicely.*

- **Gaming time display:** The friendly `h m s` sensors are text; use the separate numeric minute sensors for graphs or numeric automations.
