# Gaming budgets & bonuses

[← Back to features](../../README.md#feature-gaming-budgets) · [All guides](../README.md)

<table>
  <tr>
    <td width="32%" valign="middle">
      <img src="../assets/illustrations/gaming-budgets-portrait.webp" width="100%" alt="King-dad giving golden gaming-time bonus coins to his two unimpressed children and the HAL robot">
    </td>
    <td valign="middle">
      <h3>By royal decree: bonus minutes for everyone!</h3>
      <p>Our king loves handing out bonus minutes. The weekly limit, however, refuses to bow.</p>
    </td>
  </tr>
</table>

Even royal decrees have rules: bonus time goes to the child's PC you choose, not every gaming device in the kingdom.

**Development preview:** Daily and weekly limits and **Add 30 minutes** exist in preview source. Check your installed version first.

## Set a gaming limit

1. In Home Assistant, open **Settings → Devices & services → SmartHouse Parental Control**.
2. Open your child's **PC device page**.
3. Set **Daily limit** and **Weekly limit**.
4. Check the gaming-time readings with a short game session.

**Daily and weekly limits are separate.** A child may have minutes left today but still reach the weekly limit.

## Give extra time

Press **Add 30 minutes** for the chosen PC to grant **30 more minutes today**.

For example: 180 daily minutes + 30 bonus minutes = **210 minutes today**. The weekly limit stays the same, and time already played is still recorded. The bonus resets at the next Home Assistant local midnight.

Royal generosity does not override the calendar.

## Other options

- **Unlimited gaming:** Bypasses applicable limits without deleting playtime history.
- **Weekend bonus:** Extra daily weekend minutes are planned. An older **Weekend daily limit** option works differently — it *replaces* the normal limit. Check your version.
- **Screen idle bonus:** [Planned](screen-idle-bonus.md). Eligible inactive time before screen-off could earn extra daily minutes.
- **Budget Overview:** [Planned](budget-overview.md). One clear receipt for the family's gaming-time accountant.

## Good to know

Offline PCs can leave gaps in gaming history. **Missing data isn't zero playtime.**

Don't use budget readings alone to trigger automatic game closing. Test the exact PC and version first.

*The +10 coins in the cartoon are royal decoration, not another released button.*

**For developers:** [Original technical notes](../reference/features/gaming-budgets-preview-notes.md) · [HA reference](../reference/ha_integration_technical.md).

[Track applications](tracked-applications.md) · [Controls & automations](parent-actions.md) · [Known limitations](../known_limitations.md)
