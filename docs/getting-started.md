# Getting started

[← All guides](README.md) · [← Project home](../README.md)

SmartHouse Parental Control connects your child's Windows PC to Home Assistant, so you can see gaming time, set limits and give extra minutes when you choose.

**This is a development preview, not a one-click installer.** You'll need to be comfortable testing software built from source.


> **Breaking change in HA 0.6.1:** the only integration domain is `parental_control`.
> If upgrading from `smarthouse_gaming` 0.5.x, **do not run a normal
> in-place update**. First follow the [one-time clean-cut installation
> guide](domain-clean-cut.md); saved HA settings and tracked apps must be
> configured again. The Windows/MQTT protocol stays unchanged.

## What you'll need

- A **Windows 10 or 11 (64-bit) PC** for your child.
- **Home Assistant** with MQTT and Recorder enabled.
- The [Windows companion](windows_deployment.md) and [Home Assistant integration](ha_integration.md).

Windows reports activity. Home Assistant displays it and keeps the settings.

## Get it running

1. Read [known limitations](known_limitations.md). There's no verified signed Windows installer yet. **Don't disable Windows security** to force it to install.
2. Set up the [Windows companion](windows_deployment.md). Start with **one test PC**, not every computer in the house.
3. Follow the [Home Assistant setup guide](ha_integration.md). Both systems must be able to reach your MQTT broker.
4. Check that the PC appears in Home Assistant and that **fresh activity data** arrives.
5. [Track an app](features/tracked-applications.md), [set a budget](features/gaming-budgets.md) and try the [manual parent controls](features/parent-actions.md) when safe.

**Keep automatic locking and game termination off** until you've tested your PC and version. Closing a game may lose unsaved progress.

## Coming later

[AFK grind bonuses](features/screen-idle-bonus.md) and the [itemized Budget Overview](features/budget-overview.md) are plans, not installation steps.

*Real setup screenshots are being prepared without family names or network details. [Screenshot checklist](assets/screenshots/README.md).*
