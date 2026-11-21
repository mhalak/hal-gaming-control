> **Archived engineering notes (21 November 2026).** These notes cover specific development versions and may be outdated. For the shorter parent-facing guide, [start here](../../features/gaming-budgets.md).

---

# Gaming budgets and bonus minutes

[← Documentation](../README.md) · [← Project home](../../README.md)

**Status:** Daily and weekly limits and the **Add 30 minutes** action exist in preview source; verify your installed HA version before using them. The additive Weekend bonus UI and Screen idle bonus have separate release/acceptance boundaries; do not assume every feature below is installed.

<table>
  <tr>
    <td width="42%" valign="middle">
      <img src="../assets/illustrations/gaming-budgets.webp" width="320" alt="Caricature of the king-dad granting plus-ten and plus-thirty golden gaming coins to his unimpressed kids, watched by a small friendly robot">
    </td>
    <td valign="middle">
      <h3>By royal decree: bonus minutes!</h3>
      <p>A daily budget is a rule. A parent bonus is a negotiation. A weekly cap is what happens when someone tries to negotiate seven times.</p>
      <p>With great power comes the ability to press <strong>Add 30 minutes</strong>. Use it wisely, Your Majesty.</p>
    </td>
  </tr>
</table>

*Illustration only — not a screenshot of Home Assistant. Coin denominations are visual storytelling, not additional released bonus buttons.*

## Set the basic limits

1. In Home Assistant, go to **Settings → Devices & services → SmartHouse Parental Control** and open the **device page for the desired PC**.
2. Locate **Daily limit** and **Weekly limit**. They are separate quotas; setting a daily allowance doesn't remove a stricter weekly limit.
3. Set the allowances and check the current **Daily gaming time**, **Weekly gaming time**, **Daily budget**, and **Weekly budget** entities where available in your installed preview.
4. Confirm the behavior with a short real-device test before enabling any restrictions or external automation. **No automatic enforcement should be enabled just because a budget sensor exists.**

The older **Weekend daily limit** option *replaces* the daily allowance and is not the same as the newer *additive* **Weekend bonus**. Upgrading between versions requires a safe migration. See [HA integration details](../ha_integration.md) and [product direction](../product_direction.md).

## Give a parent bonus

Select **Add 30 minutes** on the child's PC. Each confirmed press grants another 30 minutes to **that day's daily allowance**; it resets on the Home Assistant local calendar's next midnight.

It **does not add 30 minutes to the weekly limit**, and it does not erase already measured gaming time. For example, a 180-minute daily limit plus one 30-minute parent bonus means 210 daily minutes available, subject to the remaining weekly allowance.

**Unlimited gaming** is a separate override: it bypasses applicable restrictions without erasing tracked usage. Use it deliberately; it isn't the same as resetting the clock.

## Understand the numbers

- **Measured gaming time**: how much tracked, confirmed time has been accounted for the period (subject to coverage limitations).
- **Daily budget**: today's allowance, including applicable bonuses.
- **Weekly budget**: an independent cap on usage during the week.
- **Weekend bonus (target model)**: extra daily minutes on each weekend day; no rollover to Monday.
- **Screen idle bonus (planned)**: additional *daily* allowance from eligible inactivity before Windows turned the display off. It is **not** a reduction of recorded gaming time. [Explanation](screen-idle-bonus.md).

An itemized textual [Budget overview](budget-overview.md) is planned. Until released, use the actual preview entities, their attributes and the release-specific guide rather than assuming the proposed display exists.

## Screenshots

**Screenshot pending — capture on a version-verified, sanitized test installation:**

1. PC device page showing Daily limit, Weekly limit and gaming-time/budget entities.
2. Parent pressing **Add 30 minutes**, then the reflected daily allowance.
3. Weekend bonus controls **only after** the additive UI is actually released.

[How to capture screenshots safely](../assets/screenshots/README.md)

## Common questions

**Why is there time left today but the child still cannot play?** The weekly limit or another active restriction can independently prevent gaming.

**Why did the number not change while the PC was offline?** Missing telemetry may mean incomplete coverage. Don't interpret unknown as zero and don't invent historical gaming time.

**Did the Screen idle bonus rewrite the activity history?** No. It is a policy bonus granted by the parent, not a measurement correction.

### Related
[Manual actions](parent-actions.md) · [Budget overview — planned](budget-overview.md) · [Screen idle bonus — planned](screen-idle-bonus.md) · [Release history](../ha_releases.md)
