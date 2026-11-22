# Gaming budgets & bonuses

[← Feature index](../../README.md#feature-gaming-budgets) · [All guides](../README.md)

[Track applications →](tracked-applications.md)

<table>
  <tr>
    <td width="32%" valign="middle">
      <img src="../assets/illustrations/gaming-budgets-portrait.webp" width="100%" alt="King-dad giving golden gaming-time bonus coins to his two unimpressed children and the HAL robot">
    </td>
    <td valign="middle">
      <h3>By royal decree: bonus minutes for everyone!</h3>
      <p>Our king loves handing out bonus minutes. The weekly budget, however, refuses to bow.</p>
    </td>
  </tr>
</table>

Even royal decrees have rules: bonus time goes to the child's PC you choose, not every gaming device in the kingdom.

**Development preview (HA 0.5.11):** Daily budget, Weekly budget, Weekend bonus and **Add 30 minutes** are available in source. Test the installed version on your own PC.

## Set the gaming budgets

1. In Home Assistant, open **Settings → Devices & services → SmartHouse Parental Control**.
2. Open your child's **PC device page**.
3. Set **Daily budget** (0–600 min, 10-minute steps) and **Weekly budget** (0–4200 min, 60-minute steps).
4. Check the gaming-time readings with a short game session.

**Daily and weekly budgets are separate.** A child may have minutes left today but still reach the weekly budget. The separate **Daily budget remaining** and **Weekly budget remaining** sensors report their unused percentages.

## Give extra time

Press **Add 30 minutes** for the chosen PC to grant **30 more minutes today**.

For example: 180 daily minutes + 30 bonus minutes = **210 minutes today**. The weekly budget stays the same, and time already played is still recorded. The bonus resets at the next Home Assistant local midnight.

Royal generosity does not override the calendar.

## Allowed gaming hours

The per-PC **Configuration** section now includes **Schedule enabled** and **Allowed from** / **Allowed until** time pickers (HA 0.5.13). The window defines when gaming is allowed; both Gaming rules enabled and Schedule enabled must be ON for a passive restriction outside the window. Overnight windows are supported; equal start/end mean all day. This does not alter accrued game time or issue any Windows commands.

## Other options

- **Unlimited gaming:** Bypasses applicable budgets without deleting playtime history.
- **Weekend bonus:** Configure 0–600 extra minutes (10-minute steps), added to the Daily budget on each Saturday and Sunday. For example, 120 daily + 60 weekend = 180 min on each weekend day. Weekly budget is unchanged. The obsolete **Weekend daily limit** replacement rule is retired; old stored values are ignored and the new bonus starts at 0 until you change it.
- **Screen idle bonus:** [Planned](screen-idle-bonus.md). Eligible inactive time before screen-off could earn extra daily minutes.
- **Budget Overview:** [Planned](budget-overview.md). One clear receipt for the family's gaming-time accountant.

## Good to know

**Daily gaming time** and **Weekly gaming time** are readable text sensors (for example, `11h 51m 3s` instead of `711m 3s`). Their separate **Daily gaming time (minutes)** / **Weekly gaming time (minutes)** numeric duration sensors remain available under diagnostics for graphs and automations. The numeric value is still in **minutes**. The underlying accounting still counts confirmed seconds. Offline PCs can leave gaps in gaming history. **Missing data isn't zero playtime.**

Don't use budget readings alone to trigger automatic game closing. Test the exact PC and version first.

*The +10 coins in the cartoon are royal decoration, not another released button.*

**Preview clean start:** Budget numbers use new entity IDs; older *_limit number and old percent-budget sensor entities are retired from the entity registry. Existing Recorder history is not purged. Fresh installations default to a 4200-minute weekly allowance; older saved unlimited (-1) values stay unlimited until configured; the new weekly slider accepts only 0–4200 in 60-minute steps.

**For developers:** [Original technical notes](../reference/features/gaming-budgets-preview-notes.md) · [HA reference](../reference/ha_integration_technical.md).

More: [Controls & automations](parent-actions.md) · [Known limitations](../known_limitations.md)

---

**Explore more features:** [Track applications →](tracked-applications.md)
