# Budget Overview

[← Feature index](../../README.md#feature-budget-overview) · [All guides](../README.md)

[← AFK grind](screen-idle-bonus.md)

<table>
  <tr>
    <td width="132" valign="middle">
      <img src="../assets/illustrations/budget-overview.webp" width="120" alt="Dad reviewing a detailed HAL gaming budget with mum watching unimpressed beside a Do Not Disturb desk sign">
    </td>
    <td valign="middle">
      <h3>Budget Review — DO NOT DISTURB</h3>
      <p>The family gaming-time auditor has receipts. Mum is distinctly unimpressed. The breakdown below is an illustration of a planned feature, not live data.</p>
    </td>
  </tr>
</table>

**Budget Review — DO NOT DISTURB.** Dad has the numbers. Mum has questions. No one is allowed to interrupt the audit.

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

[Gaming budgets](gaming-budgets.md) · [AFK grind](screen-idle-bonus.md)

---

**Explore more features:** [← AFK grind](screen-idle-bonus.md) · [Feature index](../../README.md#feature-budget-overview)
