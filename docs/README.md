# Documentation

[← Back to the fun part: project home](../README.md)

Welcome to the useful part of the manual. The front page makes promises; these pages explain what actually exists, how to use it, and where the dragons are.

> **Development preview:** always check the [release history](ha_releases.md) and [known limitations](known_limitations.md) before installing. Planned features are marked **Planned**. A documented design is not a shipped feature.

## Start here

1. [Home Assistant setup and daily use](ha_integration.md) — install the integration and understand device controls.
2. [Windows companion deployment](windows_deployment.md) — install and validate the Windows service on a gaming PC.
3. [Tracked applications](features/tracked-applications.md) — add Roblox, Minecraft, or another application in Home Assistant.
4. [Gaming budgets and bonuses](features/gaming-budgets.md) — daily/weekly limits and parent-granted minutes.
5. [Manual parental actions](features/parent-actions.md) — Lock PC, Terminate game and precautions.

## Feature guides

| Feature | Status | Guide |
| --- | --- | --- |
| Track an application, including non-games | HA application editor in preview; full end-to-end acceptance pending | [Tracked applications](features/tracked-applications.md) |
| Daily and weekly gaming budgets, Add 30 minutes | Preview; verify your installed version | [Gaming budgets](features/gaming-budgets.md) |
| Lock PC and Terminate game | Limited manual smoke tests passed | [Manual actions](features/parent-actions.md) |
| Screen idle bonus / overnight AFK grinding | **Planned — not implemented** | [Screen idle bonus](features/screen-idle-bonus.md) |
| Human-readable itemized Budget overview | **Planned — not implemented** | [Budget overview](features/budget-overview.md) |

The guides describe both the *parent-facing behavior* and any important implementation limitations. They never assume that a proposed feature is installed.

## Screenshots

Real screenshots belong next to the procedure they explain, not on the landing page. See the [screenshot capture checklist](assets/screenshots/README.md). Capture images from a validated preview deployment, strip children's names, PC names, MQTT addresses, tokens and other personal data, and keep filenames stable. Until a real image is captured, the guides show a clearly labeled screenshot placeholder **in text only**.

## Under the hood

- [Product direction and architecture decisions](product_direction.md) — future behavior and design constraints.
- [MQTT protocol](mqtt_protocol.md) — transport, state and privacy.
- [Foreground accounting and migration](foreground_migration.md) — source of gaming-time readings and historical boundaries.
- [Recorder coverage](recorder_coverage.md) — what happens when telemetry is missing.
- [Windows deployment](windows_deployment.md), [Home Assistant integration](ha_integration.md) and [MQTT troubleshooting](mqtt_setup.md).
- [Release history](ha_releases.md), [known limitations](known_limitations.md) and [release checklist](hacs_release.md).

## For contributors

This is a source-only preview, not a supported public binary distribution. Review source changes and pass required CI before considering deployment. Test the Windows companion on real machines, use one-PC pilots, preserve private credentials, and don't bypass OS security protections.

Feedback, reproducible bugs and sanitized screenshots can be proposed through [GitHub issues](https://github.com/mhalak/smarthouse-parental-control/issues). Please include versions and observable behavior, not household infrastructure details.

*Powered by HAL Systems. The documentation is serious about security so the front page doesn't have to be.*
