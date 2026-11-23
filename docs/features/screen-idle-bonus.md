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

**End-to-end source preview — automatically enabled, not yet hardware-validated.** Windows observes logical console **ON / DIM / OFF**, timeout and session idle. HA applies a verified display gate automatically, with a separate replay-safe **daily** Screen idle bonus journal. There is no setting to disable it; devices with unknown/unsupported display observations continue normal verified foreground accounting. It requires verified measured gaming time and a plausible **automatic Windows timeout**, not simply an OFF packet. A console OFF report is not proof that every physical monitor is dark, and gamepads/manual power-off still require supervised real-PC tests. [Design issue #92](https://github.com/mhalak/hal-gaming-control/issues/92).

## How would it work?

1. A child leaves a game running and walks away.
2. Until Windows **confirms the screen is off**, gaming time still counts.
3. Once the screen is off, the PC could stay awake and keep grinding, but **new screen-off minutes would stop counting as playtime**.
4. HA automatically grants a **daily bonus** for reliably verified eligible inactive minutes **before** the screen turned off.

The bonus adds to today's allowance. **It doesn't erase recorded playtime or raise the weekly limit.**

## An example

The child leaves Roblox at **16:30**, but the screen stays on until **16:40**. Those 10 minutes are still recorded.

If reliable data confirms the child wasn't playing, HA automatically awards **+10 daily minutes**. Once the screen is off, no new playtime would count while it stays off.

The PC must stay **awake** for the game to continue. Screen off is not the same as Windows sleep.

## What needs testing?

Manually switching off a monitor must not invent bonus minutes. Missing information must not earn a reward. Gamepads, multiple monitors, reconnections and games that prevent screen-off also need testing.

This is implemented in source, but edge cases still need real-PC validation. The robot never invents an idle bonus when evidence is missing.

**For developers:** [Original design notes](../reference/features/screen-idle-bonus-preview-notes.md).

More: [Gaming budgets](gaming-budgets.md)

---

**Explore more features:** [← Controls & automations](parent-actions.md) · [Budget Overview →](budget-overview.md)

## Developer reference — Unified MQTT v3 (HA 0.13.1+)

Screen Idle is an automatic **bonus feature**, not an optional telemetry protocol. HA and Windows both use the mandatory, non-retained **Unified v3** monitoring stream at `SmartHouse/Gaming/<Windows-computer-name>/state/telemetry`. There is **no** separate `state/display_context` or `state/foreground_identity` subscriber and no v2 compatibility setting.

Each v3 snapshot contains distinct, strictly validated nested `foreground` and `display` objects, alongside `system` uptime. The `display` block includes the logical Windows console state (`on`, `dim`, `off` or `unknown`), event epoch/sequence, observation and event ages, AC/DC display timeout settings, power source and last input idle age. See the exact [shared v3 wire fixture](../../tests/contracts/v3/telemetry-foreground.json) and [full monitoring contract](../unified_mqtt_telemetry.md).

The Windows helper uses `GUID_CONSOLE_DISPLAY_STATE` notifications and `GetLastInputInfo`; missing or ambiguous observations become `unknown`. HA applies validated console OFF before foreground accounting, suspending new measured gaming seconds but never deleting already-confirmed usage. After ON, a subsequent verified foreground sample is required. Retained, replayed, stale and foreign packets cannot grant time.

### Automatic daily Screen Idle bonus

There is no Screen idle configuration page, acknowledgement or opt-out. The v3 monitoring stream and evidence-qualified Screen idle policy are **always active**. If a PC reports only an `unknown` display state, verified gaming time still counts normally, but it receives no speculative Screen idle bonus.

An eligible, recent ON→OFF event needs a fresh confirmed measured gaming interval, event freshness, plausible AC/DC timeout, independent idle evidence and an unambiguous helper receipt. Gaps, unknown power source, manual-off ambiguity and missing evidence fail closed. Eligible whole minutes are capped at 120 per event and 180 per local HA day. A device-scoped `screen_idle_bonus_journal` prevents duplicate grants across reconnect and restart. This increases daily allowance only; it cannot erase played seconds or affect the weekly cap.

**Validation:** physical Windows SYSTEM + interactive-session tests, game-controller and multiple-monitor acceptance remain outstanding. No Windows protection should be disabled for testing.

[Protocol contract](../mqtt_protocol.md) · [Issue #92](https://github.com/mhalak/hal-gaming-control/issues/92) · [Clean-cut issue #201](https://github.com/mhalak/hal-gaming-control/issues/201)
