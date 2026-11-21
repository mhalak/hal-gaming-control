# Getting started (development preview)

[← Documentation](README.md) · [← Project home](../README.md)

This is the shortest safe route from "interesting GitHub project" to a tested Home Assistant device. It is **not** a one-click consumer installer yet.

## 1. Know what you're installing

SmartHouse Parental Control has two parts:

- **Windows companion** on each child gaming PC: reports local telemetry and receives explicit parent-requested actions.
- **Home Assistant integration**: keeps per-PC tracked-app names, gaming budgets, history and parent-facing controls. It uses your existing MQTT integration.

The system is local-first. See [architecture and privacy details](mqtt_protocol.md).

## 2. Check prerequisites and release safety

You need a supported Home Assistant instance with MQTT and Recorder, and a Windows 10/11 x64 PC able to reach the MQTT broker.

**Important:** this is a source-only development preview. There is **no verified public signed Windows installer**. Smart App Control has blocked an unsigned build in testing. Don't disable operating-system protections to force installation. If you're not equipped for source builds and controlled pilots, follow the [release history](ha_releases.md) and [known limitations](known_limitations.md) instead of deploying to a family PC.

## 3. Install and verify the Windows companion

Follow the [Windows deployment guide](windows_deployment.md), including source revision/build verification, MQTT credentials, backups, and a **single-PC pilot**.

Do not assume an agent is working merely because its files were copied. Confirm that the actual service starts and that fresh device-scoped telemetry reaches Home Assistant.

## 4. Install and configure Home Assistant

Follow the [Home Assistant integration guide](ha_integration.md). HACS installs **only** the Home Assistant side; it cannot install the Windows service on the child's PC.

Create or select the correct device and confirm that it is reporting fresh, coherent data. Do not enable automated game termination or locking during initial setup.

## 5. Set up your family's rules

1. [Track an application](features/tracked-applications.md), such as Roblox or Minecraft, using the **HA-only** list and its two-step Add → Save changes flow.
2. [Set daily and weekly budgets](features/gaming-budgets.md), and test the 30-minute parent bonus if available on your installed version.
3. Learn the difference between the explicit [Lock PC and Terminate game](features/parent-actions.md) actions.

Once the source and your deployment are validated, evaluate policy enforcement separately; don't infer that every experimental feature is active just because it is described in this repository.

## Coming later

[Screen idle bonus / overnight AFK support](features/screen-idle-bonus.md) and [itemized Budget overview](features/budget-overview.md) are **planned**, not installation steps today.

## Screenshots

Real step-by-step screenshots are being prepared from a sanitized test environment. See the [capture plan](assets/screenshots/README.md); no fake screenshots or sensitive family data will be published.
