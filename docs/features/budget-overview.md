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

This is a **native Home Assistant vertical-stack dashboard**, not a custom frontend. The large number and status appear first, followed by a horizontal daily remaining bar, the itemized receipt and a separate weekly bar. The dashboard does not issue commands or silently change your rules.

1. In **Settings → Devices & services → HAL Gaming Control**, open the target PC. Find the real entity IDs for **Daily budget remaining**, **Weekly budget remaining** and **Gaming restriction**.
2. Open an editable dashboard, choose **Add card → Manual** and paste the full YAML below.
3. Replace the example entity IDs with those from *that same PC* (every `sensor.example_pc_...` and `binary_sensor.example_pc_...`). The example names are placeholders, not guaranteed IDs.
4. Check the daily and weekly percentages against the sensors. Test with rules disabled, unlimited gaming, exhausted weekly allowance and offline/unknown data before trusting the display.

```yaml
type: vertical-stack
cards:
  - type: markdown
    title: "🎮 Gaming budget — Today"
    content: |-
      {% set d = 'sensor.example_pc_daily_budget_remaining' %}
      {% set r = 'binary_sensor.example_pc_gaming_restriction' %}
      {% set mode = state_attr(d, 'daily_budget_status') %}
      {% set left = state_attr(d, 'daily_remaining_minutes') %}
      {% if mode is none %}
      **⚪ Budget data unavailable** — check the integration and PC.
      {% elif mode == 'disabled' %}
      **⚪ Gaming rules disabled** — no restrictions are applied.
      {% elif mode == 'unlimited' %}
      **♾️ Unlimited gaming** — no finite daily countdown.
      {% elif is_state(r, 'on') %}
      **🔴 Gaming restricted** — {{ state_attr(r, 'reasons') | join(', ') if state_attr(r, 'reasons') else 'check active rules' }}.
      {% elif is_state(r, 'off') %}
      **🟢 Gaming permitted by active rules**.
      {% else %}
      **⚪ Restriction status unknown** — cannot confirm if play is allowed.
      {% endif %}
      {% if mode == 'limited' %}

      # {{ left if left is number else 'Unknown' }} min remaining today
      {% endif %}

  - type: tile
    entity: sensor.example_pc_daily_budget_remaining
    name: "Daily budget remaining (%)"
    features:
      - type: bar-gauge
        min: 0
        max: 100

  - type: markdown
    title: "🧾 Today's allowance"
    content: |-
      {% set e = 'sensor.example_pc_daily_budget_remaining' %}
      {% set mode = state_attr(e, 'daily_budget_status') %}
      {% set idle = state_attr(e, 'screen_idle_bonus_minutes') %}
      {% if mode is none %}
      **No verified budget snapshot.**
      {% elif mode == 'disabled' %}
      **Gaming rules are disabled.** No active allowance is enforced.
      {% elif mode == 'unlimited' %}
      **Unlimited daily gaming.** The recorded time remains unchanged.
      {% else %}
      | Source | Minutes |
      |:--|--:|
      | Base daily budget | {{ state_attr(e, 'base_daily_minutes') }} |
      | Weekend bonus | +{{ state_attr(e, 'weekend_bonus_minutes') }} |
      | Parent bonus | +{{ state_attr(e, 'parent_bonus_minutes') }} |
      | Screen idle bonus | {{ ('+' ~ idle ~ ' min') if idle is number else 'Not available yet' }} |
      | **Total daily allowance** | **{{ state_attr(e, 'daily_limit_minutes') }}** |
      | Measured gaming time | {{ ('−' ~ state_attr(e, 'daily_used_minutes') ~ ' min') if state_attr(e, 'daily_used_minutes') is number else 'Unknown' }} |
      | **Remaining today** | **{{ (state_attr(e, 'daily_remaining_minutes') ~ ' min') if state_attr(e, 'daily_remaining_minutes') is number else 'Unknown' }}** |
      {% endif %}
      {% if state_attr(e, 'weekly_budget_status') == 'limited' %}

      **Weekly remaining:** {{ state_attr(e, 'weekly_remaining_minutes') if state_attr(e, 'weekly_remaining_minutes') is number else 'Unknown' }} / {{ state_attr(e, 'weekly_limit_minutes') }} min
      {% elif state_attr(e, 'weekly_budget_status') == 'unlimited' %}

      **Weekly limit:** Unlimited
      {% endif %}
      {% if state_attr(e, 'coverage_incomplete') == true %}

      ⚠️ **Coverage incomplete:** only verified gaming time is counted; gaps may exist.
      {% endif %}

  - type: tile
    entity: sensor.example_pc_weekly_budget_remaining
    name: "Weekly budget remaining (%)"
    features:
      - type: bar-gauge
        min: 0
        max: 100
```

The horizontal bars display **percentage remaining**, not elapsed minutes. They may be unknown when rules are disabled, a limit is unlimited, or the data is unavailable. This is expected and different from 0%.

For the activity status we deliberately read the existing **Gaming restriction** sensor, because daily remaining minutes alone cannot say whether the weekly budget, playing hours or a per-game limit currently blocks gaming. When its reading is unavailable, the card explicitly says *unknown* rather than claiming that play is allowed.

The standard Home Assistant **Device info** page cannot host injected Markdown. The stack belongs on a Lovelace dashboard, and it uses existing device entities without duplicating unique IDs.

## Data and privacy

The daily sensor exposes the base allowance, Weekend bonus, Parent bonus, currently unimplemented Screen idle bonus, total effective daily limit, measured daily time, remaining daily time and the independent weekly ledger in its attributes. It also reports whether the policy is disabled/unlimited and whether historical coverage is incomplete.

This is a **read-only view** of HAL Gaming Control's existing local HA accounting. No Windows agent change, additional cloud service or second application is required. Bonuses never rewrite history or add minutes to the weekly cap.

More: [Gaming budgets](gaming-budgets.md) · [Screen idle bonus](screen-idle-bonus.md)

---

**Explore more features:** [← AFK grind](screen-idle-bonus.md) · [Feature index](../../README.md#feature-budget-overview)
