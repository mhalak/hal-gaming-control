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

**Native Budget overview (Undo) (HA 0.13.10+ source).** Each Windows device has one built-in allowance dropdown inside **Settings → Devices & services → HAL Gaming Control → your PC → Controls**. It shows the base allowance, each Parent and Screen off bonus in time order, a read-only separator, the **∑ TOTAL** daily allowance, today's **Gaming Session** (cumulative verified daily playtime), another separator and **∑ Remaining Budget** as the final read-only row. **∑ TOTAL** remains the always-selected default. The former text sensor in **Sensors** has been retired because the native device page clipped its multiline content. The full structured receipt remains available in the **Daily budget remaining** attributes, and the optional dashboard YAML below provides a richer read-only breakdown.

**Daily usage stays HA-owned and validated.** If today's gaming-time evidence is missing, no Parent bonus can be revoked. The dropdown cannot disable individual rows visually, so informational rows do nothing except reject action. Only actionable Parent bonus rows carry a red **⛔** suffix. After a permitted administrator click, HA revokes that single bonus immediately and returns the displayed value to **∑ TOTAL**. No separate confirmation buttons, remote Windows commands or duplicate accounting store.

## The gaming-time receipt

Here is what a parent's daily budget might look like:

| Item | Minutes |
| --- | ---: |
| Daily allowance | 180 |
| Weekend bonus | +30 |
| Parent bonus | +30 |
| Screen idle bonus | +0 (example) |
| **Total daily allowance** | **240** |
| Measured gaming time | −200 |
| **Remaining today** | **40** |

*Illustrative values, not live measurements.* Automatic Screen idle bonus grants require verified eligible Windows OFF events; no events means no bonus, not a fabricated grant.

## Parent bonus history and Undo (HA 0.9.0, #165)

Every **new** click of **Add 30 minutes** becomes a separate, timestamped Parent bonus grant. The daily sensor exposes the **12 most recent** active grants (`parent_bonus_grants_today`) and active/cancelled records (`parent_bonus_activity_today`) to keep Recorder attributes compact. The full 90-day audit remains in the per-PC config entry, and the native select can list all active grants for today. The sensor also exposes `parent_bonus_recent_action` (latest add or cancellation), so the dashboard gives immediate visible feedback after a change. Cancelled grants remain in the audit; no past gaming time is erased.

Previous bonuses were just an anonymous `bonus_minutes` total. These remain as a **Legacy Parent bonus** row, with unknown individual grant times. We never invent earlier clicks.

### Safely undo one specific bonus

The native **Budget overview (Undo)** dropdown preserves the original HA select unique ID from Parent bonus Undo, so existing device associations remain intact. Its rows are ordered as a transparent receipt:

```text
+ 180 min - Daily Budget
+  30 min - Parent Bonus (11:40)
+  10 min - Screen Off Bonus (12:50)
+  30 min - Parent Bonus (14:00)      ⛔
──────────
∑ 250 min - TOTAL
 − 170 min - Gaming Session
───────────
∑  80 min - Remaining Budget
```

Only **⛔** items can be removed; all other entries are information only, including both separator lines. The **red ⛔ appears at the end** of the Parent bonus row only while cancellation is permitted. **∑ TOTAL** is always the selected/default row, including after an administrator cancels a bonus. **∑ Remaining Budget** stays visible as a read-only final line. The amount updates immediately. Same-minute, same-size bonuses are distinguished as `(11:40 #1)` / `(11:40 #2)`, **never by displaying their opaque grant IDs**. Internally cancellation still targets the full immutable journal ID. Numeric columns use Unicode figure spaces and actionable rows have a padded gap before the red ⛔. Since HA's native Select is a plain-text control, the icon cannot be pinned precisely to the right edge in every screen width/font.


**Displayed minute precision:** The numbers come from the existing, verified HA daily accounting. `Gaming Session` means the total gaming time **today**, not just the current uninterrupted session. Since the native Select accepts plain text only, consumed minutes are rounded **up** and remaining minutes **down** for a conservative whole-minute receipt; the underlying rules, bonus eligibility, and Recorder remain exact to the second. If confirmed daily usage is missing, both rows say **Unknown**, never 0 minutes. Disabled/unlimited budgets show a clear text status instead of inventing a remaining figure. When the device reports incomplete historical coverage, the displayed consumed time is only a verified lower bound. The two **shorter** separators are separate, unique, read-only option labels (10 and 11 characters); HA cannot render real HTML dividers in a built-in select.

**How Undo works:** an authenticated HA administrator selects a Parent bonus marked ⛔ and the integration immediately cancels that entire bonus, without Prepare/Confirm buttons. It rechecks the current accounting **after refreshing the coordinator**. A Parent bonus is no longer cancellable once even one verified gaming second has consumed it, or if removing it would leave used time greater than the reduced daily allowance. A resulting balance of exactly zero is allowed. The allocation convention is **base allowance first, then existing bonus grants by chronological order**; it is not a claim that individual gaming seconds physically carry bonus IDs. If a PC's usage is unknown, Undo fails closed. Other users and anonymous/automation calls cannot remove a bonus because the integration checks the authenticated HA administrator context.

**Home Assistant limitation:** the standard Select entity cannot gray out individual read-only rows. Clicking a non-removable item is rejected without changing allowances. No cloud or custom frontend is involved.

**Release status:** The extended native receipt is allocated to HA source **0.13.10 / Preview 34**. Verify the published version and installed HA version separately.

## Add a Home Assistant dashboard card

This is a **native Home Assistant vertical-stack dashboard**, not a custom frontend. The large number and status appear first, followed by a horizontal daily remaining bar, the itemized receipt and a separate weekly bar. The accounting/receipt is read-only except for explicitly marked ⛔ Parent bonus actions in the native dropdown. Those actions require an HA administrator and never issue Windows commands.

1. In **Settings → Devices & services → HAL Gaming Control**, open the target PC. Find the real entity IDs for **Daily budget remaining**, **Weekly budget remaining**, **Gaming restriction**, and **Budget overview (Undo)**.
2. Open an editable dashboard, choose **Add card → Manual** and paste the full YAML below.
3. Replace the example entity IDs with those from *that same PC* (every `sensor.example_pc_...`, `binary_sensor.example_pc_...` and `select.example_pc_...`). The example names are placeholders, not guaranteed IDs.
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
      {% set left = state_attr(d, 'daily_remaining_seconds') %}
      {% if mode is none %}
      **⚪ Budget data unavailable** — check the integration and PC.
      {% elif mode == 'disabled' %}
      **⚪ Gaming rules disabled** — no restrictions are applied.
      {% elif state_attr(d, 'unlimited_gaming_active') == true %}
      **♾️ Unlimited gaming ON** — all automatic gaming restrictions are bypassed. Confirmed gaming time is still recorded.
      {% elif is_state(r, 'on') %}
      **🔴 Gaming restricted** — {{ state_attr(r, 'reasons') | join(', ') if state_attr(r, 'reasons') else 'check active rules' }}.
      {% elif mode == 'unlimited' %}
      **♾️ Daily quota disabled** — weekly, schedule and per-game limits may still apply. This alone does not confirm playing is permitted.
      {% elif is_state(r, 'off') %}
      **🟢 Gaming permitted by active rules**.
      {% else %}
      **⚪ Restriction status unknown** — cannot confirm if play is allowed.
      {% endif %}
      {% if mode == 'limited' %}

      {% if left is number %}
      # {{ (left // 60) | int }}m {{ (left % 60) | int }}s remaining today
      {% else %}
      # Remaining gaming time unknown
      {% endif %}
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
      {% elif state_attr(e, 'unlimited_gaming_active') == true %}
      **Unlimited gaming ON.** All automatic restrictions are bypassed; measured gaming time is still recorded.
      {% elif mode == 'unlimited' %}
      **Daily quota disabled.** Weekly, schedule and per-game limits may still apply.
      {% else %}
      | Source | Minutes |
      |:--|--:|
      | Base daily budget | {{ state_attr(e, 'base_daily_minutes') }} |
      | Weekend bonus | +{{ state_attr(e, 'weekend_bonus_minutes') }} |
      | Parent bonus | +{{ state_attr(e, 'parent_bonus_minutes') }} |
      | Screen idle bonus | {{ ('+' ~ idle ~ ' min') if idle is number else 'Not available yet' }} |
      | **Total daily allowance** | **{{ state_attr(e, 'daily_limit_minutes') }}** |
      | Measured gaming time | {{ ('−' ~ state_attr(e, 'daily_used_minutes') ~ ' min') if state_attr(e, 'daily_used_minutes') is number else 'Unknown' }} |
      {% set left = state_attr(e, 'daily_remaining_seconds') %}
      | **Remaining today** | **{{ ((left // 60) | int) ~ 'm ' ~ ((left % 60) | int) ~ 's' if left is number else 'Unknown' }}** |
      {% endif %}
      {% if state_attr(e, 'weekly_budget_status') == 'limited' %}

      {% set weekly_left = state_attr(e, 'weekly_remaining_seconds') %}
      **Weekly remaining:** {{ (((weekly_left // 60) | int) ~ 'm ' ~ ((weekly_left % 60) | int) ~ 's') if weekly_left is number else 'Unknown' }} / {{ state_attr(e, 'weekly_limit_minutes') }} min
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

  - type: markdown
    title: "👑 Parent bonus history"
    content: |-
      {% set e = 'sensor.example_pc_daily_budget_remaining' %}
      {% set entries = state_attr(e, 'parent_bonus_activity_today') or [] %}
      {% set legacy = state_attr(e, 'parent_bonus_legacy_minutes') | int(0) %}
      {% set last = state_attr(e, 'parent_bonus_recent_action') %}
      **Parent bonus today: +{{ state_attr(e, 'parent_bonus_minutes') | int(0) }} min**
      {% if last %}

      **Latest action:** {{ as_local(as_datetime(last.at_utc)).strftime('%H:%M') }} ·
      {% if last.action == 'cancelled' %}↩️ −{{ last.minutes }} min cancelled{% else %}✅ +{{ last.minutes }} min added{% endif %}
      {% endif %}
      {% if legacy > 0 %}

      Legacy bonus (time unknown): **+{{ legacy }} min**
      {% endif %}
      {% for grant in entries %}

      {{ as_local(as_datetime(grant.created_at_utc)).strftime('%H:%M') }} ·
      +{{ grant.minutes }} min · {{ grant.status | upper }} ·
      `{{ grant.id[-10:] }}`
      {% else %}

      No new individual grants yet.
      {% endfor %}

  - type: entities
    title: "Budget overview — direct Undo"
    entities:
      - entity: select.example_pc_parent_bonus_to_undo
        name: "Choose ⛔ to cancel a Parent bonus"

  - type: markdown
    content: |-
      {% set s = 'select.example_pc_parent_bonus_to_undo' %}
      **Latest action:** {{ state_attr(s, 'undo_status') or 'No recent changes' }}

```

The horizontal bars display **percentage remaining**, not elapsed minutes. They may be unknown when rules are disabled, a limit is unlimited, or the data is unavailable. This is expected and different from 0%.

For the activity status we deliberately read the existing **Gaming restriction** sensor, because daily remaining minutes alone cannot say whether the weekly budget, playing hours or a per-game limit currently blocks gaming. When its reading is unavailable, the card explicitly says *unknown* rather than claiming that play is allowed.

The standard Home Assistant **Device info** page cannot host injected Markdown. The stack belongs on a Lovelace dashboard, and it uses existing device entities without duplicating unique IDs.

## Data and privacy

The daily sensor exposes the base allowance, Weekend bonus, Parent bonus, automatic verified Screen idle bonus, total effective daily limit, measured daily time, remaining daily time and the independent weekly ledger in its attributes. It also exposes `unlimited_gaming_active` to distinguish the parent override (all automatic restrictions bypassed) from simply having no finite daily quota (weekly, schedule and per-game restrictions may still apply). It also reports whether the policy is disabled/unlimited and whether historical coverage is incomplete.

This is a **read-only view** of HAL Gaming Control's existing local HA accounting. No Windows agent change, additional cloud service or second application is required. Bonuses never rewrite history or add minutes to the weekly cap.

More: [Gaming budgets](gaming-budgets.md) · [Screen idle bonus](screen-idle-bonus.md)

---

**Explore more features:** [← AFK grind](screen-idle-bonus.md) · [Feature index](../../README.md#feature-budget-overview)
