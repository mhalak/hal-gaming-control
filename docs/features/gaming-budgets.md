# Gaming budgets & bonuses

[← Feature index](../../README.md#feature-gaming-budgets) · [All guides](../README.md)

[← Local mode](local-mode.md) · [Track applications →](tracked-applications.md)

<table>
  <tr>
    <td width="32%" valign="middle">
      <img src="../assets/illustrations/gaming-budgets-portrait.webp" width="100%" alt="King-dad giving golden gaming-time bonus coins to his two unimpressed children and the HAL robot">
    </td>
    <td valign="middle">
      <h3>By royal decree: bonus minutes for everyone!</h3>
      <p>Our king loves handing out bonus minutes. Smart Parent Bonus adjusts only the limits that need to move.</p>
    </td>
  </tr>
</table>

Even royal decrees have rules: bonus time goes to the child's PC you choose, not every gaming device in the kingdom.

**Development preview (HA 0.7.0):** Daily budget, Weekly budget, Weekend bonus and **Add 30 minutes** are available in source. Test the installed version on your own PC.

## Set the gaming budgets

1. In Home Assistant, open **Settings → Devices & services → HAL Gaming Control**.
2. Open your child's **PC device page**.
3. Set **Daily budget** (0–600 min, 10-minute steps) and **Weekly budget** (0–4200 min, 60-minute steps).
4. Check the gaming-time readings with a short game session.

**Daily and weekly budgets are separate.** The new **Gaming budget remaining** sensor combines the active daily quota, weekly quota and allowed-hour deadline: the smallest finite remaining allowance is the effective budget. Quotas decrease with verified gaming time; an allowed-hour deadline approaches even while idle. The separate **Daily budget remaining** and **Weekly budget remaining** percentage sensors still exist.

## Give extra time

Press **Add 30 minutes** for the chosen PC, or call the existing Add bonus action with 1–600 minutes. With verified accounting and enabled finite rules, Smart Parent Bonus grants that much additional *effective* time, adjusting each active limit by only its necessary shortfall. Configured recurring quotas and hours are unchanged.

| Remaining daily / weekly / allowed window (min) | Effective before → after +30 | Temporary adjustments (min) |
| --- | --- | --- |
| 120 / 300 / 360 | 120 → 150 | Daily +30 |
| 0 / 20 / 15 | 0 → 30 | Daily +30, weekly +10, schedule +15 |
| 180 / 60 / 360 | 60 → 90 | Weekly +30 |
| 60 / 120 / 15 | 15 → 45 | Schedule +30 |

A schedule bonus extends the absolute end of the current window. At 21:45, a +30-minute schedule-limited grant changes a 22:00 deadline to 22:30. The extended clock runs even when the child is not playing. At 22:30 the extension expires; it is not a bank of unused gaming minutes. A fresh grant after an expired window can reopen it from the grant time. As a conservative source-preview policy, a grant before the first allowed window of the local day is rejected rather than silently opening it early.

Daily adjustments reset at local midnight, weekly adjustments at the next local Monday, and schedule extensions at their absolute deadline (including across midnight). A quota reset can therefore change the effective limiter during a temporary overnight window. Screen idle and Weekend bonuses remain daily-only. Unknown/offline accounting, disabled rules or no finite effective limit reject new smart grants; they do not invent remaining time. Unlimited gaming remains a separate override.

Each grant is one transaction, not three separate bonuses. See [Budget Overview and Undo](budget-overview.md) for the receipt, original grant history and cancellation rules. Existing legacy daily grants are preserved.

**Source preview (#241):** requires an installed build containing the smart-control changes. No release or deployment is implied.

### Sync bonus with other devices — the sibling peace treaty

**Planned ([#276](https://github.com/mhalak/hal-gaming-control/issues/276)).** “How come she gets more time than me?!” The king no longer needs a calculator. Press **Sync bonus with other devices** on the PC that needs a top-up: if one child has received 37.5 bonus minutes today and the other has received 30, the selected PC gets exactly 7.5 minutes. Nobody loses time, and pressing the button again adds nothing once the bonuses match.

The proposed comparison uses today's active Parent bonuses and verified Screen idle bonuses, not remaining playtime, regular budgets, Weekend bonus or unlimited overrides. Smart Parent Bonus will adjust the applicable limits only as needed. The top-up will be recorded as one grant in Budget Overview, with the normal Undo rules. This is a one-time parent action, not continuous synchronization or a shared gaming budget. Gaming penalties and persistent suspensions, if introduced separately, are not bonus entitlements: this proposed action must not copy, lift or propagate them between PCs.

## Allowed gaming hours

The PC's Configuration section has **Schedule enabled** plus two independent allowed-hour windows: **Weekday allowed from/until** (Mon–Fri) and **Weekend allowed from/until** (Sat–Sun). Weekend hours initially inherit the saved weekday hours until explicitly edited, avoiding policy changes on upgrade. The daily windows may cross midnight, anchored to their starting day; they use HA local time. **Gaming rules enabled** must also be ON for schedule restrictions to apply. They never alter recorded gaming time or issue Windows commands.

## Other options

- **Unlimited gaming:** Bypasses applicable budgets without deleting playtime history.
- **Weekend bonus:** Configure 0–600 extra minutes (10-minute steps), added to the Daily budget on each Saturday and Sunday. For example, 120 daily + 60 weekend = 180 min on each weekend day. Weekly budget is unchanged. The obsolete **Weekend daily limit** replacement rule is retired; old stored values are ignored and the new bonus starts at 0 until you change it.
- **Screen idle bonus:** [Automatically enabled](screen-idle-bonus.md) on HA 0.13.1+. When evidence proves eligible inactivity before a Windows screen-OFF event, a daily bonus can be granted. Since HA 0.13.4, fresh OFF observations keep new gaming time paused even when the OFF transition happened hours earlier. Neither bonus nor OFF detection changes historical usage or the weekly limit.
- **Budget Overview:** [Source preview](budget-overview.md) (#93). Native dashboard receipt with daily/weekly gauges and itemized bonuses; only available after the corresponding HA integration update.

## Good to know

**Daily gaming time** and **Weekly gaming time** are readable text sensors (for example, `11h 51m 3s` instead of `711m 3s`). Their separate **Daily gaming time (minutes)** / **Weekly gaming time (minutes)** numeric duration sensors remain available under diagnostics for graphs and automations. The numeric value is still in **minutes**, but starting with HA 0.13.13 it shows only **completed whole minutes** (e.g. 59m 37s → `59 min`, not 60). The underlying accounting and actual restriction thresholds still use confirmed seconds, and missing/invalid readings remain unavailable. Offline PCs can leave gaps in gaming history. **Missing data isn't zero playtime.**

**Uptime** appears as a readable `d h m s` text in Direct MQTT on HA 0.13.13 and in native MQTT once Windows agent 0.4.1 refreshes its existing discovery entry. The entity ID is preserved, but its former numeric Uptime state changes to text; use the `uptime_seconds` attribute (Direct MQTT) or `system_uptime_seconds` on **Active game** for numeric values. **Gaming restriction** uses supported gamepad icons for permitted/restricted/unknown states; an icon is not itself an authorization signal.

Don't use budget readings alone to trigger automatic game closing. Test the exact PC and version first.

*The +10 coins in the cartoon are royal decoration, not another released button.*

**Preview clean start:** Budget numbers use new entity IDs; older *_limit number and old percent-budget sensor entities are retired from the entity registry. Existing Recorder history is not purged. Fresh installations default to a 4200-minute weekly allowance; older saved unlimited (-1) values stay unlimited until configured; the new weekly slider accepts only 0–4200 in 60-minute steps.

**For developers:** [Original technical notes](../reference/features/gaming-budgets-preview-notes.md) · [HA reference](../reference/ha_integration_technical.md).

More: [Controls & automations](parent-actions.md) · [Known limitations](../known_limitations.md)

---

**Explore more features:** [← Local mode](local-mode.md) · [Track applications →](tracked-applications.md)
