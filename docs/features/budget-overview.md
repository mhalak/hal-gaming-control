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

The Budget Overview is the family's gaming-time receipt. It shows the **currently limiting allowance**, each **extra bonus**, the **gaming time already used**, and **what's left**. No guessing, no mental arithmetic, and no digging through a dozen Home Assistant sensors.

Some extra minutes come **directly from a parent** — yes, Dad, pressing **Add 30 minutes** counts. Others can be **awarded automatically**, based on parent-approved rules and verified activity, such as eligible screen-idle time. The **Weekend bonus** has its own line too. Every bonus has a source, and none of them secretly erases time already played.

So if the kids somehow have *another hour*, we can finally ask: **Did the little rascals find a loophole, or has Dad been handing out bonus minutes like candy?** Mum wants the receipts.

It's a transparent breakdown, **not an automatic cheat detector**. Unusual numbers should be easy to question, while all active limits still apply.

**Native Budget overview (Undo) (HA 0.13.12+ source).** Each Windows device has one built-in allowance dropdown inside **Settings → Devices & services → HAL Gaming Control → your PC → Controls**. It shows the base allowance, each Parent and Screen off bonus in time order, then **∑ TOTAL** as the always-selected effective allowance, **Gaming Session** (cumulative verified playtime for the displayed daily or weekly period), and **∑ Remaining Budget** as the final read-only row. There are **no divider lines** in the native dropdown. **∑ TOTAL** remains the always-selected default. The former text sensor in **Sensors** has been retired because the native device page clipped its multiline content. The full structured receipt remains available in the **Daily budget remaining** attributes, and the optional dashboard YAML below provides a richer read-only breakdown.

**Daily usage stays HA-owned and validated.** If today's gaming-time evidence is missing, no Parent bonus can be revoked. The dropdown cannot disable individual rows visually, so informational rows do nothing except reject action. Only actionable Parent bonus rows carry a red **⛔** suffix. After a permitted administrator click, HA revokes that single bonus immediately and returns the displayed value to **∑ TOTAL**. No separate confirmation buttons, remote Windows commands or duplicate accounting store.

## Smart Budget Overview (#241, #242)

The native receipt follows the effective limiting constraint. A weekly-limited receipt uses weekly usage, a daily-limited receipt uses daily usage, and a schedule-limited receipt uses verified daily playtime plus the remaining allowed window. Ties are deterministic. **TOTAL − Gaming Session = Remaining Budget**, including after whole-minute display rounding.

At 21:45 with 60 minutes already played and a 22:00 deadline:

```text
+  60 min - Daily Budget (Schedule Adjusted)
+  15 min - Until Schedule Limit
∑  75 min - TOTAL
−  60 min - Gaming Session
∑  15 min - Remaining Budget
```

After a +30-minute parent grant the deadline becomes 22:30, TOTAL becomes 105 and remaining becomes 45. At 22:10 with continuous play the used time is 85 and remaining is 20. If instead the child remains idle after the grant, the original window expires, 10 unused bonus minutes appear as **Expired Schedule Bonus**, TOTAL is 80, used is 60 and remaining is 20. No expired minutes are recorded as playtime.

Each smart grant is one transaction. Its displayed contribution depends on the selected constraint; the original requested amount is retained even when the selected contribution is smaller. Weekly carry can appear on later days but cannot be revoked outside its original local grant day. Consumed quota or elapsed attributable schedule extension locks cancellation. An eligible Undo replays dependent grants without erasing measured usage. Legacy daily grants are preserved and become read-only when today's smart grants depend on them.

Use the **Gaming budget remaining** sensor (numeric minutes) for automations. Its attributes include exact `remaining_seconds`, `limiting_budget`, `limiting_sources`, `budget_status`, `effective_budget_minutes`, `used_minutes`, `remaining_percent` and `schedule_end`. Zero, disabled, unlimited and unknown are distinct. The legacy daily/weekly percentages remain independent; do not add the original requested smart-grant total to the configured daily quota.

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

Every **new** click of **Add 30 minutes** becomes a separate, timestamped Parent bonus grant. The daily sensor exposes the **12 most recent** active grants (`parent_bonus_grants_today`) and active/cancelled records (`parent_bonus_activity_today`) to keep Recorder attributes compact. The audit (90-day expired-history retention, with active dependencies preserved) remains in the per-PC config entry, and the native select can list all active grants for today. The sensor also exposes `parent_bonus_recent_action` (latest add or cancellation), so the dashboard gives immediate visible feedback after a change. Cancelled grants remain in the audit; no past gaming time is erased.

Previous bonuses were just an anonymous `bonus_minutes` total. These remain as a **Legacy Parent bonus** row, with unknown individual grant times. We never invent earlier clicks.

### Safely undo one specific bonus

The native **Budget overview (Undo)** dropdown preserves the original HA select unique ID from Parent bonus Undo, so existing device associations remain intact. Its rows are ordered as a transparent receipt:

```text
+ 180 min - Daily Budget
+  30 min - Parent Bonus (11:40)
+  10 min - Screen Off Bonus (12:50)
+  30 min - Parent Bonus (14:00)      ⛔
∑ 250 min - TOTAL
− 170 min - Gaming Session
∑  80 min - Remaining Budget
```

Only **⛔** items can be removed; all other entries, including TOTAL, Gaming Session and Remaining Budget, are information only. The **red ⛔ appears at the end** of the Parent bonus row only while cancellation is permitted. **∑ TOTAL** is always the selected/default row, including after an administrator cancels a bonus. **∑ Remaining Budget** stays visible as a read-only final line. The amount updates immediately. Same-minute, same-size bonuses are distinguished as `(11:40 #1)` / `(11:40 #2)`, **never by displaying their opaque grant IDs**. Internally cancellation still targets the full immutable journal ID. Numeric columns use Unicode figure spaces and actionable rows have a padded gap before the red ⛔. Since HA's native Select is a plain-text control, the icon cannot be pinned precisely to the right edge in every screen width/font.


**Displayed minute precision:** The numbers come from verified HA accounting for the displayed period. `Gaming Session` means the total verified gaming time for the displayed day or week, not just the current uninterrupted session. Since the native Select accepts plain text only, consumed minutes are rounded **up** and remaining minutes **down** for a conservative whole-minute receipt; the underlying rules, bonus eligibility, and Recorder remain exact to the second. If confirmed daily usage is missing, both rows say **Unknown**, never 0 minutes. Disabled/unlimited budgets show a clear text status instead of inventing a remaining figure. When the device reports incomplete historical coverage, the displayed consumed time is only a verified lower bound. No divider rows are used: the standard HA Select is plain text, and a cleaner list works better in the mobile UI. The debit starts with **− as the first character**, followed by one Unicode figure space before the number.

**How Undo works:** an authenticated HA administrator selects a Parent bonus marked ⛔ and the integration immediately cancels that entire bonus, without Prepare/Confirm buttons. It rechecks the current accounting **after refreshing the coordinator**. A Parent bonus is no longer cancellable once even one verified gaming second has consumed it, or if removing it would leave used time greater than the reduced applicable allowance. A resulting balance of exactly zero is allowed. The allocation convention is **base allowance first, then existing bonus grants by chronological order**; it is not a claim that individual gaming seconds physically carry bonus IDs. If a PC's usage is unknown, Undo fails closed. Other users and anonymous/automation calls cannot remove a bonus because the integration checks the authenticated HA administrator context.

**Home Assistant limitation:** the standard Select entity cannot gray out individual read-only rows. Clicking a non-removable item is rejected without changing allowances. No cloud or custom frontend is involved.

**Release status:** The simplified native receipt is allocated to HA source **0.13.12 / Preview 36**. Verify the published version and installed HA version separately.

## Add a Home Assistant dashboard card

Use the native effective sensor and receipt instead of reconstructing quotas with Jinja. Add an **Entities** card and select the matching PC's Gaming budget remaining, Budget overview (Undo), Daily budget remaining and Weekly budget remaining. Check actual entity IDs on the device page. The previous daily-only arithmetic is not valid for multi-limit grants; the native receipt is the authoritative itemized display. No custom frontend is needed.

## Data and privacy

The daily sensor exposes the base allowance, Weekend bonus, Parent bonus, automatic verified Screen idle bonus, total effective daily limit, measured daily time, remaining daily time and the independent weekly ledger in its attributes. It also exposes `unlimited_gaming_active` to distinguish the parent override (all automatic restrictions bypassed) from simply having no finite daily quota (weekly, schedule and per-game restrictions may still apply). It also reports whether the policy is disabled/unlimited and whether historical coverage is incomplete.

This is a **read-only view** of HAL Gaming Control's existing local HA accounting. No Windows agent change, additional cloud service or second application is required. Bonuses never rewrite history; smart grants can temporarily extend the effective weekly cap without changing its configured value.

More: [Gaming budgets](gaming-budgets.md) · [Screen idle bonus](screen-idle-bonus.md)

---

**Explore more features:** [← AFK grind](screen-idle-bonus.md) · [Feature index](../../README.md#feature-budget-overview)
