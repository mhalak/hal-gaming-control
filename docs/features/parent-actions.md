# Parent controls and Home Assistant automations

[← Documentation](../README.md) · [← Project home](../../README.md)

**Status:** **Lock PC** and **Terminate game** have passed limited live smoke testing as explicit actions in the development preview. That is not a guarantee for every PC, game or installation.

> Manual buttons settle the occasional dispute. Home Assistant automations are the magic that could save your nerves before the next "five more minutes" debate. The robot can referee; the parents still make the rules.

## Before you press anything

Confirm that you've selected the **correct child's PC** in Home Assistant, that its Windows agent is healthy, and that you're not about to interrupt unsaved progress.

## Lock PC

Use **Lock PC** on the device page to request a Windows workstation lock. It is not a permanent ban; the Windows user can unlock normally. A locked screen is not proof that a running process has terminated.

## Terminate game

Use **Terminate game** to request termination of configured matching game processes. This can immediately close the game and **lose unsaved progress**. Do not use it as a casual test while someone is building something important.

Tracked application enrollment and remote termination are distinct operations. Adding a safe display name in HA must never, on its own, cause a Windows action.

## The real magic: native Home Assistant automations

The two buttons are the manual fallback. The **biggest advantage of a Home Assistant integration** is that parents can define their own automations instead of trusting a hidden, one-size-fits-all punishment engine. Want a notification first? A grace period? A gentle warning before the dramatic finale? Home Assistant already knows how to orchestrate those steps. That is the kind of magic that saves parental nerves — and removes the need to personally negotiate "just five more minutes" for the seventh time.

**Example of the intended workflow (not yet a verified end-to-end feature):** once a fresh, device-scoped **Gaming restriction active** signal is available and validated, a native HA automation could notify the family, wait briefly, confirm the restriction is *still active*, then optionally invoke **Terminate game** or **Lock PC**. Or it could simply notify a parent and leave the decision to them. The parent owns the rule, timing and consequence.

**Important implementation boundary:** The integration does not silently publish automatic termination or lock commands. The dedicated restriction trigger and automatic enforcement flow still need release/real-device acceptance. Ordinary budget sensors alone are **not** reliable authorization to terminate a game; unknown or unavailable telemetry is **not** a confirmed restriction. Keep destructive automations **disabled** until the exact version, trigger freshness and behavior have been tested with disposable sessions. [See the version-specific HA integration reference](../ha_integration.md#automation-only-command-execution--050-preview).

## Screenshots

**Screenshot pending:** sanitized HA device page showing the two manual buttons and a simple confirmation of which PC is selected. Avoid user/PC names or local network details.

### Related
[Gaming budgets](gaming-budgets.md) · [Windows deployment](../windows_deployment.md) · [Known limitations](../known_limitations.md)
