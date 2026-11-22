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

**Planned — not implemented.** The itemized Budget Overview isn't available in Home Assistant yet. [Design issue #93](https://github.com/mhalak/smarthouse-parental-control/issues/93).

## Where did the time go?

The idea is simple: one easy-to-read receipt for your child's PC.

| Item | Minutes |
| --- | ---: |
| Daily allowance | 180 |
| Weekend bonus | +30 |
| Parent bonus | +30 |
| Screen idle bonus | +10 |
| Time played | −200 |
| **Time left today** | **50** |

*The numbers are examples, not live Home Assistant data. Some bonuses shown here are still planned.*

Each bonus has its own line. Bonus minutes **don't remove playtime already recorded**.

## Where would I see it?

The first version is planned as a **Home Assistant dashboard card**. No extra add-on should be needed.

**Weekly limits stay separate.** Extra minutes today don't add to the week's allowance.

Dad may now close the spreadsheet. Mum has been waiting.

**For developers:** [Original design notes](../reference/features/budget-overview-preview-notes.md).

More: [Gaming budgets](gaming-budgets.md)

---

**Explore more features:** [← AFK grind](screen-idle-bonus.md) · [Feature index](../../README.md#feature-budget-overview)
