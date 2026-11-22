# Guides

[← Project home](../README.md)

Want to track an app, set a limit or give bonus time? You're in the right place.

**Before you start:** This project is a **development preview**. Some features are ready to try; others are ideas we're building. See [what works and what's still missing](known_limitations.md).

## Start here

**Upgrading from any earlier HA preview (0.5.x, 0.6.0 or 0.6.1)?** Follow the [HA 0.7.0 clean-cut guide](domain-clean-cut.md). A normal in-place update is unsupported.

1. [Getting started](getting-started.md) — what you need and how to test safely.
2. [Home Assistant setup](ha_integration.md) — find your PC, apps and controls.
3. [Windows installation](windows_deployment.md) — for people comfortable building software from source.

## Explore the features

| Feature | What you can expect |
| --- | --- |
| [100% Local mode](features/local-mode.md) | Windows service + local MQTT + Home Assistant; no external cloud control service |
| [Gaming budgets & bonuses](features/gaming-budgets.md) | Daily/weekly budgets and additive Weekend bonus in HA 0.5.11 preview |
| [Track applications](features/tracked-applications.md) | App list and friendly names in preview |
| [Controls & automations](features/parent-actions.md) | Manual controls tested; automatic enforcement still needs testing |
| [AFK grind](features/screen-idle-bonus.md) | **Planned** |
| [Budget Overview](features/budget-overview.md) | **Source preview (#93):** native HA dashboard receipt; verify installed version |

Every feature starts with one of our family cartoons. **The jokes are real; the pictures are illustrations, not screenshots of a finished feature.**

## Need help?

Check the [version-by-version changelog](changelog.md) (**breaking changes highlighted**), [known limitations](known_limitations.md), [technical HA release history](ha_releases.md) or the [real screenshot plan](assets/screenshots/README.md). Please keep children's names and home-network details out of bug reports.

## For contributors

This is a source-only preview. Feedback and reproducible bugs are welcome through [GitHub issues](https://github.com/mhalak/hal-gaming-control/issues). Please share versions and what happened, not private family or network data.

## For developers

Looking for code and implementation details? See [Windows deployment](windows_deployment.md), [MQTT and privacy](mqtt_protocol.md), [Windows MQTT OTA transport (default-off)](mqtt_ota.md), [Recorder coverage](recorder_coverage.md), [Home Assistant engineering reference](reference/ha_integration_technical.md) and [older issue history](reference/known_limitations_history.md). The feature guides also link to their earlier technical notes. For the AI-assisted development numbers (and a truly heroic token bill), see the [AI development cost report](ai-development-cost.md).

*Powered by HAL Systems. Serious about safety, less serious about the last 30 minutes.*
