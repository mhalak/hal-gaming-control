# AFK grind & Screen idle bonus

[← Feature index](../../README.md#feature-screen-idle-bonus) · [All guides](../README.md)

[← Controls & automations](parent-actions.md) · [Budget Overview →](budget-overview.md)

<table>
  <tr>
    <td width="32%" valign="middle">
      <img src="../assets/illustrations/screen-idle-bonus.webp" width="100%" alt="Smiling blond boy asleep while a game grinds in the background and a robot waves its finger at dad checking his watch">
    </td>
    <td valign="middle">
      <h3>The loot won't mine itself ⛏️</h3>
      <p>Kid asleep. Minecraft's working the night shift like it has a mortgage. Our robot refuses to bill the gaming budget for a pickaxe's overtime.</p>
    </td>
  </tr>
</table>

As responsible parents, we want our kids to succeed. And the loot isn't going to mine itself. The game can work the night shift — the gaming budget shouldn't have to.

**Windows preview only — not deployed.** The agent now listens for Windows **console display ON / DIM / OFF** notifications in the signed-in user session, together with the existing AC/DC power-plan timeout and input-idle context. This is NOT proof that every physical monitor is off or that Windows switched it off automatically. **The Screen idle bonus and HA policy are not implemented.** [Design issue #92](https://github.com/mhalak/hal-gaming-control/issues/92).

## How would it work?

1. A child leaves a game running and walks away.
2. Until Windows **confirms the screen is off**, gaming time still counts.
3. Once the screen is off, the PC could stay awake and keep grinding, but **new screen-off minutes would stop counting as playtime**.
4. Parents could optionally grant a **daily bonus** for eligible inactive minutes **before** the screen turned off.

The bonus adds to today's allowance. **It doesn't erase recorded playtime or raise the weekly limit.**

## An example

The child leaves Roblox at **16:30**, but the screen stays on until **16:40**. Those 10 minutes are still recorded.

If reliable data confirms the child wasn't playing, the parent could award **+10 daily minutes**. Once the screen is off, no new playtime would count while it stays off.

The PC must stay **awake** for the game to continue. Screen off is not the same as Windows sleep.

## What needs testing?

Manually switching off a monitor must not invent bonus minutes. Missing information must not earn a reward. Gamepads, multiple monitors, reconnections and games that prevent screen-off also need testing.

Until then, this is a plan, not a promise. Even the robot knows better than to guess.

**For developers:** [Original design notes](../reference/features/screen-idle-bonus-preview-notes.md).

More: [Gaming budgets](gaming-budgets.md)

---

**Explore more features:** [← Controls & automations](parent-actions.md) · [Budget Overview →](budget-overview.md)

## Developer preview — Windows display context

In the Windows agent source, `display_context.py` reads `VIDEOIDLE` for the active power plan using Win32 power APIs, reporting configured **AC** and **DC** timeouts in seconds. `0` means Windows is configured to **never** turn the display off automatically on that power source. The foreground helper (which runs in the active interactive user session, not Session 0) separately reads `GetLastInputInfo` and returns the approximate age in milliseconds of the last session input. Failures, a locked or unconfirmed session, or input-age ambiguity yield `null` rather than fabricated activity.

The agent can publish a non-retained, 45-second-expiry, device-scoped MQTT JSON snapshot on `SmartHouse/Gaming/<device_id>/state/display_context` approximately every 30 seconds after its normal telemetry is synchronized. The schema is:

```json
{
  "version": 1,
  "device_id": "example_pc",
  "observed_at": 1790000000.0,
  "display_state": "off",
  "display_scope": "windows_console",
  "display_event_age_ms": 1500,
  "ac_timeout_seconds": 600,
  "dc_timeout_seconds": 300,
  "power_source": "ac",
  "last_input_idle_ms": 120000
}
```

Values are illustrative, not readings from a family PC. An interactive-user helper registers a hidden, non-focus-stealing Windows top-level window using `RegisterPowerSettingNotification(GUID_CONSOLE_DISPLAY_STATE)`, and reports console `on`, `dim`, `off` or `unknown` with `display_event_age_ms`. It invalidates stale/locked-session, sleep/resume, topology-change and missing-event results to `unknown`. All values share this existing `display_context` JSON packet; no new HA entities were introduced. **A console `off` event cannot prove all physical monitors are off**, does not distinguish automatic from manual off, and `GetLastInputInfo` cannot reliably see every game controller. Neither timeout nor state by itself authorizes a Screen idle bonus. A real SYSTEM + interactive-user pilot and later HA source-of-truth accounting are still needed. No Windows power setting or game process is modified.

[High-priority issue #176](https://github.com/mhalak/hal-gaming-control/issues/176) covers future consolidation of **all** Windows monitoring into one versioned per-PC JSON snapshot. The present Windows change stays on the existing display-context topic until HA and Windows can migrate their authoritative gaming telemetry together, without double-counting.
