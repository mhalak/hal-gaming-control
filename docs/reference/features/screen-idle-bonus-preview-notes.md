> **Archived engineering notes (21 November 2026).** These notes cover specific development versions and may be outdated. For the shorter parent-facing guide, [start here](../../features/screen-idle-bonus.md).

---

# Screen idle bonus — AFK grind support

[← Documentation](../README.md) · [← Project home](../../README.md)

**Status: planned; not implemented.** See [design issue #92](https://github.com/mhalak/smarthouse-parental-control/issues/92). There is currently no Screen idle bonus setting to turn on, no automatic award on deployed PCs, and no released screen-off telemetry guarantee.

<table>
  <tr>
    <td width="132" valign="middle">
      <img src="../assets/illustrations/screen-idle-bonus.webp" width="120" alt="Smiling blond boy asleep while a game grinds in the background and a robot waves its finger at dad checking his watch">
    </td>
    <td valign="middle">
      <h3>The loot won't mine itself</h3>
      <p>Kid asleep, computer grinding, robot explaining why the clock should not keep charging playtime. A future idea, not an available switch.</p>
    </td>
  </tr>
</table>

*Conceptual illustration only — not a screenshot of Home Assistant or proof of released behavior.*

> **As responsible parents, we want our children to succeed in the world.** And the loot isn't going to mine itself. So while the family sleeps, a digital employee can put in the night shift. We support the grind; we just don't think the gaming budget needs to pull overtime.

## What problem does it solve?

Children leave a foreground game running, walk away and eventually Windows switches off the monitor. They are not actively playing, but they also didn't close the game.

There are two equally valid parenting philosophies:

- **Generous parent:** "Nice grind. Here's a Screen idle bonus for eligible minutes you left the game running."
- **Strict parent:** "You left the game running. Your budget noticed."

This is **not a software measurement error**. The child did leave the tracked game in the foreground. The bonus is a deliberate parent-controlled allowance, while the original measured minutes remain visible.

## Planned behavior

1. The Windows companion observes the tracked foreground application and Windows display power events, without changing the child's power settings or game process.
2. When Windows **confirms the display is off**, the application can keep running for AFK grinding, but the Home Assistant **Active game** should become confirmed `idle` and new screen-off minutes should **stop consuming gaming time**. Off is not the same as Sleep; the PC must remain awake for grinding.
3. If the parent has enabled the future automatic bonus policy, HA uses reliable *last real user activity* evidence to determine the **eligible inactivity before display-off**. It can award those already-measured minutes as a **Screen idle bonus** to today's daily allowance.
4. The measured daily, weekly and per-app gaming time **is not rewritten or reduced**. The bonus increases today's *daily budget only*. Weekly restrictions remain independent.
5. On confirmed user return and a fresh foreground observation, normal tracked gameplay accounting resumes. No game is closed, no PC is locked and no Windows-side rules are changed.

### Example timeline

| Time | Observation | Intended accounting |
| --- | --- | --- |
| 16:00 | Roblox in foreground | Gaming time counts |
| 16:30 | Child walks away, Roblox stays open | Time still counts |
| 16:40 | Windows confirms automatic display-off after 10 idle minutes | Stop new gaming-time counting; **optionally add +10 min Screen idle bonus** for the eligible pre-off window |
| 23:00 | Roblox still grinding, display remains off | No additional screen-off gaming time |
| Next user return | Display wakes and fresh foreground identity confirms Roblox | Gaming time resumes |

For the 16:00–16:40 interval, **40 minutes remain recorded**, not 30. If eligible and parent-approved, the daily allowance grows by 10. The bonus is **not** an extra weekly allowance.

## How will Windows detect it?

The planned Windows agent approach uses power notifications such as `GUID_CONSOLE_DISPLAY_STATE` to distinguish ON, OFF, DIM and unknown, plus the active Windows screen-off timeout for context. Reliable inactivity evidence must come from the **interactive user's session** (the service session alone cannot infer it). No keystrokes, passwords, browsing URLs or full command lines should travel to Home Assistant.

This is deliberately conservative:

- A manual monitor power-off immediately after activity **does not** manufacture an entire timeout's worth of bonus.
- Missing, stale or ambiguous screen-off/inactivity telemetry **does not** earn speculative minutes.
- A game may prevent the display turning off; that case needs explicit later handling, not a falsely confirmed screen-off.
- Sleep, multi-monitor configurations, gamepads, display cables, reconnection, midnight/DST and repeated MQTT events require real-world acceptance.
- HA must grant each qualifying bonus event **only once**, even across restarts or replays.

## Where will the parent see it?

The [planned itemized Budget overview](budget-overview.md) will show `+ Screen idle bonus` alongside base allowance, parent bonus and any weekend bonus. It will also show **measured gaming time unchanged** and the resulting daily and weekly balances.

**Screenshot planned after implementation and real-device testing:**
1. Parent setting to enable/disable automatic Screen idle bonuses.
2. An awarded bonus entry in the child's Budget overview.
3. A confirmed `idle` Active game state while the display is off.

These are **future screenshots**, not images of a working current feature. Follow the [sanitized screenshot guide](../assets/screenshots/README.md).

### Related
[Gaming budgets](gaming-budgets.md) · [Budget overview](budget-overview.md) · [Product direction](../product_direction.md) · [Issue #92](https://github.com/mhalak/smarthouse-parental-control/issues/92)
