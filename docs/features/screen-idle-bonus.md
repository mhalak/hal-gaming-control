# AFK grind & Screen idle bonus

[← Back to features](../../README.md#what-can-it-do) · [All guides](../README.md)

<p align="center">
  <img src="../assets/illustrations/screen-idle-bonus.webp" width="300" alt="Smiling blond boy asleep in bed while his PC keeps grinding, as dad checks his watch and the HAL robot wags a finger">
</p>

**Planned — not implemented.** There is no Screen idle bonus switch or verified screen-off tracking feature to enable today. See [design issue #92](https://github.com/mhalak/smarthouse-parental-control/issues/92).

As responsible parents, we want our kids to succeed. And the loot isn't going to mine itself. So here's the plan: let the game grind while the child sleeps, without pretending the child is still playing.

## How it would work

1. A child leaves a game running and walks away.
2. Until Windows **confirms the screen is off**, recorded gaming time still counts.
3. With the screen confirmed off, the PC can stay awake and the game can continue running, but **new screen-off minutes would stop consuming the gaming budget**.
4. Parents could optionally award a **daily Screen idle bonus** for eligible inactive minutes **before** screen-off.

The bonus **adds allowance**. It never removes or rewrites measured playtime, and it does **not** increase the weekly limit.

## A simple example

The child stops using Roblox at **16:30**, but the screen stays on until **16:40**.

Those 10 minutes are still recorded. If reliable inactivity evidence confirms they qualify, a parent could grant **+10 daily bonus minutes**. After the screen goes off, no new gaming time would count while it stays off.

The computer must remain **awake** for the game to grind. A sleeping PC is not the same as a screen that is off.

<details>
<summary>Technical design & edge cases</summary>

- The proposed Windows companion would use display-state notifications, such as **GUID_CONSOLE_DISPLAY_STATE**, plus reliable inactivity from the interactive user session.
- A manual monitor switch-off must **not** invent bonus minutes. Stale or uncertain data must not earn a bonus.
- Games that block screen-off, gamepads, multiple monitors, Windows Sleep, reconnection, midnight and daylight-saving changes all require testing.
- Each qualifying bonus event must be granted **once**, including after reconnects and restarts.
- No keystrokes, passwords, browsing URLs or full command lines should be sent to Home Assistant.
- On confirmed return to the PC, fresh foreground activity would resume normal accounting.
- A future [Budget Overview](budget-overview.md) would show the bonus and measured time separately. Real screenshots must wait until implementation and testing.

</details>

*The “AFK GRIND” screen is an illustration, not a working Home Assistant feature.*

[Gaming budgets](gaming-budgets.md) · [Budget Overview](budget-overview.md) · [Product direction](../product_direction.md)
