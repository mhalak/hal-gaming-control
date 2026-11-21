# Manual parent actions

[← Documentation](../README.md) · [← Project home](../../README.md)

**Status:** **Lock PC** and **Terminate game** have passed limited live smoke testing as explicit actions in the development preview. That is not a guarantee for every PC, game or installation.

> You can ask nicely. You can ask again. Or you can ask Home Assistant to press the button. The button is still your responsibility.

## Before you press anything

Confirm that you've selected the **correct child's PC** in Home Assistant, that its Windows agent is healthy, and that you're not about to interrupt unsaved progress.

## Lock PC

Use **Lock PC** on the device page to request a Windows workstation lock. It is not a permanent ban; the Windows user can unlock normally. A locked screen is not proof that a running process has terminated.

## Terminate game

Use **Terminate game** to request termination of configured matching game processes. This can immediately close the game and **lose unsaved progress**. Do not use it as a casual test while someone is building something important.

Tracked application enrollment and remote termination are distinct operations. Adding a safe display name in HA must never, on its own, cause a Windows action.

## Automatic consequences?

Not part of this guide. The integration is moving toward a fresh **restriction signal** that parents can use to create their own explicit Home Assistant automations. Do not assume the presence of a budget sensor enables or validates automatic game termination; leave destructive automations off until the source, deployment and test coverage are accepted.

## Screenshots

**Screenshot pending:** sanitized HA device page showing the two manual buttons and a simple confirmation of which PC is selected. Avoid user/PC names or local network details.

### Related
[Gaming budgets](gaming-budgets.md) · [Windows deployment](../windows_deployment.md) · [Known limitations](../known_limitations.md)
