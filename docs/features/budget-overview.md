# Budget Overview

[← Feature index](../../README.md#feature-budget-overview) · [All guides](../README.md)

[← AFK grind](screen-idle-bonus.md)

<table>
  <tr>
    <td width="32%" valign="middle">
      <img src="../assets/illustrations/budget-overview.webp" width="100%" alt="Dad reviewing a detailed HAL gaming budget with mum watching unimpressed beside a Do Not Disturb desk sign">
    </td>
    <td valign="middle">
      <h3>Budget Review — DO NOT DISTURB</h3>
      <p>Dad brought spreadsheets.</p>
      <p>Mum: “When I said fix the kids' screen time, I didn't mean <strong>this!</strong>”</p>
    </td>
  </tr>
</table>

## Where did all those minutes come from?

The Budget Overview is the family's gaming-time receipt. It shows the **regular daily budget**, each **extra bonus**, the **gaming time already used**, and **what's left**. No guessing, no mental arithmetic, and no digging through a dozen Home Assistant sensors.

Some extra minutes come **directly from a parent** — yes, Dad, pressing **Add 30 minutes** counts. Others can be **awarded automatically**, based on parent-approved rules and verified activity, such as eligible screen-idle time. The **Weekend bonus** has its own line too. Every bonus has a source, and none of them secretly erases time already played.

So if the kids somehow have *another hour*, we can finally ask: **Did the little rascals find a loophole, or has Dad been handing out bonus minutes like candy?** Mum wants the receipts.

It's a transparent breakdown, **not an automatic cheat detector**. Unusual numbers should be easy to question, while the independent weekly budget still applies.

**Implementation under review — not released yet.** The HA Budget Overview is being implemented in [issue #93](https://github.com/mhalak/hal-gaming-control/issues/93). Do not expect these new attributes until the PR has been reviewed, merged and deployed.

## The gaming-time receipt

Here is what a parent's daily budget might look like:

| Item | Minutes |
| --- | ---: |
| Daily allowance | 180 |
| Weekend bonus | +30 |
| Parent bonus | +30 |
| Screen idle bonus | Not available yet |
| **Total daily allowance** | **240** |
| Measured gaming time | −200 |
| **Remaining today** | **40** |

*Illustrative values, not live measurements.* The Screen idle bonus remains **pending** until [Smart Idle #92](screen-idle-bonus.md) delivers a verified event ledger. Pending does not mean zero eligible time and must not be guessed.

## Add a Home Assistant dashboard card

The first version uses an ordinary **Markdown card**. There is no additional frontend integration to install. After updating HAL Gaming Control:

1. Open **Settings → Devices & services → HAL Gaming Control**, select your child's PC and find its existing **Daily budget remaining** entity.
2. Note its actual entity ID (for example, `sensor.lucija_daily_budget_remaining`).
3. Edit a dashboard, **Add card → Markdown**, switch to YAML editing if necessary and paste the example below.
4. Change only the `e` value on the first line to the actual entity ID.

```yaml
type: markdown
title: "Gaming budget — Today"
content: |
  {% set e = 'sensor.lucija_daily_budget_remaining' %}
  {% set mode = state_attr(e, 'daily_budget_status') %}
  {% set weekly_mode = state_attr(e, 'weekly_budget_status') %}
  {% set idle = state_attr(e, 'screen_idle_bonus_minutes') %}
  {% if states(e) in ['unknown', 'unavailable'] or mode is none %}
  **Budget data unavailable.** Check that the PC has reported fresh, reliable data.
  {% elif mode == 'disabled' %}
  **Gaming rules are disabled.** No active allowance is being enforced.
  {% elif mode == 'unlimited' %}
  **Unlimited daily gaming.** There is no finite daily countdown.
  {% else %}
  **Daily allowance:** {{ state_attr(e, 'base_daily_minutes') }} min

  **Weekend bonus:** +{{ state_attr(e, 'weekend_bonus_minutes') }} min

  **Parent bonus:** +{{ state_attr(e, 'parent_bonus_minutes') }} min

  **Screen idle bonus:** {% if idle is number %}+{{ idle }} min{% else %}Pending Smart Idle support{% endif %}

  ---

  **Total daily allowance:** {{ state_attr(e, 'daily_limit_minutes') }} min

  **Measured gaming time:** {{ state_attr(e, 'daily_used_minutes') if state_attr(e, 'daily_used_minutes') is number else 'unknown' }} min

  **Remaining today:** {{ state_attr(e, 'daily_remaining_minutes') if state_attr(e, 'daily_remaining_minutes') is number else 'unknown' }} min
  {% endif %}

  {% if weekly_mode == 'limited' %}
  **Weekly remaining:** {{ state_attr(e, 'weekly_remaining_minutes') if state_attr(e, 'weekly_remaining_minutes') is number else 'unknown' }} / {{ state_attr(e, 'weekly_limit_minutes') }} min
  {% elif weekly_mode == 'unlimited' %}
  **Weekly allowance:** unlimited
  {% endif %}

  {% if state_attr(e, 'coverage_incomplete') == true %}
  ⚠️ **Coverage incomplete:** offline or unverified periods may be missing from measured gaming time.
  {% endif %}
```

You can create one card per gaming PC by changing the device-specific entity ID. A daily allowance with remaining time **does not override an exhausted weekly budget or an out-of-hours restriction**. Daily and weekly restrictions continue to use exact verified seconds, not rounded dashboard figures.

The standard Home Assistant **Device info** page cannot host this injected Markdown card; add it to a dashboard instead. The existing **Daily budget remaining** and **Weekly budget remaining** sensor identities remain unchanged, including automations that already use them.

## Data and privacy

The daily sensor exposes the base allowance, Weekend bonus, Parent bonus, currently unimplemented Screen idle bonus, total effective daily limit, measured daily time, remaining daily time and the independent weekly ledger in its attributes. It also reports whether the policy is disabled/unlimited and whether historical coverage is incomplete.

This is a **read-only view** of HAL Gaming Control's existing local HA accounting. No Windows agent change, additional cloud service or second application is required. Bonuses never rewrite history or add minutes to the weekly cap.

More: [Gaming budgets](gaming-budgets.md) · [Screen idle bonus](screen-idle-bonus.md)

---

**Explore more features:** [← AFK grind](screen-idle-bonus.md) · [Feature index](../../README.md#feature-budget-overview)
