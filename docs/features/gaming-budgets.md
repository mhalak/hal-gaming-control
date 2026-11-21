# Gaming budgets & bonuses

[← Back to features](../../README.md#what-can-it-do) · [All guides](../README.md)

<p align="center">
  <img src="../assets/illustrations/gaming-budgets-portrait.webp" width="300" alt="King-dad giving golden bonus-minute coins to his two unimpressed children and the HAL robot">
</p>

**Available in development preview:** Daily and weekly limits and the **Add 30 minutes** button. Check your installed Home Assistant version before following these steps.

Set the rules, then enjoy not hearing “five more minutes” quite so often. Feeling generous? You can still play king for a day.

## Set a gaming limit

1. Open **Home Assistant → Settings → Devices & services → SmartHouse Parental Control**.
2. Open the **device page for the child's PC**.
3. Set **Daily limit** and **Weekly limit**.
4. Check the available gaming-time and budget sensors. Try a short test on the PC to confirm the readings.

**Daily and weekly limits are separate.** A child can have time left today but still reach the weekly limit.

## Give extra time

Press **Add 30 minutes** on the child's PC to grant 30 more minutes **today**.

For example, a 180-minute daily allowance becomes **210 minutes** after one bonus. The bonus does **not** increase the weekly limit or erase time already played. It expires at the next Home Assistant local midnight.

## What about other bonuses?

- **Weekend bonus:** Extra daily minutes for weekends are part of the target design. Do not assume the additive bonus is available in your installed version.
- **Screen idle bonus:** A [planned feature](screen-idle-bonus.md) for eligible inactive time before the monitor turns off. It does not remove recorded gaming time.
- **Unlimited gaming:** A separate override that bypasses applicable limits without deleting usage history.

The [itemized Budget Overview](budget-overview.md) is also **planned**, not a released screen.

<details>
<summary>Technical notes & troubleshooting</summary>

- The older **Weekend daily limit** *replaces* the normal daily allowance; it is not the planned additive **Weekend bonus**. See the [HA integration reference](../ha_integration.md) for version-specific behavior.
- If the PC is offline or telemetry is missing, recorded time may be incomplete. **Unknown is not zero.**
- Budget sensors alone must not trigger automatic game termination. Do not enable automatic enforcement before validating the exact installation.
- Real, privacy-safe screenshots are still pending. See the [screenshot checklist](../assets/screenshots/README.md) and [release history](../ha_releases.md).

</details>

*The illustration is a cartoon, not a Home Assistant screenshot. Its +10 coins do not represent an extra released button.*

[Track applications](tracked-applications.md) · [Controls & automations](parent-actions.md) · [Known limitations](../known_limitations.md)
