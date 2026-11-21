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

**Planned — not implemented.** There is no Screen idle bonus setting or validated screen-off tracking to turn on today. [Design issue #92](https://github.com/mhalak/smarthouse-parental-control/issues/92).

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
