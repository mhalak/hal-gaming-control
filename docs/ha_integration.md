> **Current protocol (HA 0.13.0+):** only Unified MQTT v3 telemetry from Windows agent 0.4.0+. There is no legacy compatibility option. See the [clean-cut upgrade](unified_mqtt_telemetry.md).

# Home Assistant setup & everyday use

[← All guides](README.md) · [← Project home](../README.md)

Home Assistant is the family's control panel: see gaming time, choose apps, give extra minutes and use manual controls. It can also handle reminders, which may save the family's last remaining nerve.

**Development preview:** These steps describe HA 0.7.0 preview source. Always check the [release history](ha_releases.md) and the version you've installed.


> **Breaking change in HA 0.7.0:** the only integration domain is `hal_gaming_control`.
> If upgrading from any earlier preview (`smarthouse_gaming` 0.5.x, `parental` 0.6.0, or `parental_control` 0.6.1), **do not run a normal
> in-place update**. First follow the [one-time clean-cut installation
> guide](domain-clean-cut.md); saved HA settings and tracked apps must be
> configured again. Current HA 0.13.0+ monitoring is Unified MQTT v3 only.

## Set it up

1. Install the integration from source or HACS, **where available**, then restart Home Assistant.
2. Make sure **MQTT** and **Recorder** are enabled.
3. Set up the [Windows companion](windows_deployment.md) on one test PC.
4. Add or select that PC in Home Assistant. Check that **fresh readings** appear.
5. Leave automatic restrictions off until you've tested the setup.

**HACS installs only the Home Assistant part.** It can't install the Windows program on your child's PC.

## Copy a device profile

Open **Settings → Devices & services → HAL Gaming Control → Configure → 📋 Profile copy** on the destination PC. Select another configured Gaming Control PC from the dropdown and press **Submit**. The source PC can be offline.

The destination's persistent policy is replaced, including tracked applications, budgets, weekday and weekend schedules, rule settings and portable Windows update channel settings. Inherited weekend schedules remain inherited. The source is unchanged, and subsequent edits are independent.

Device identity, MQTT routing, accounting history, existing bonus grants and live Unlimited override remain local to the destination. Windows installation authorization is never copied; changing the trusted update channel disables any prior authorization until explicitly re-enabled. Shared HA MQTT settings and HA automations are not copied.

## Track an app

Open **Settings → Devices & services → HAL Gaming Control**, choose the Windows hostname-based PC and select **Configure → Tracked applications**. Only fresh Unified v3 foreground samples are accepted; there is no telemetry protocol selection under Configure.

Home Assistant shows the app detected when the editor opened. It's a **snapshot**, not a live display. If the child switches apps, close and reopen the editor to see the new one.

To save an app, confirm the small **Add** dialog, then press **Save changes** in the main window too. Yes, two buttons. The robot is lobbying for fewer.

[See the app guide](features/tracked-applications.md).

## Set budgets & bonuses

Open the PC device page to find **Daily budget**, **Weekly budget**, **Weekend bonus** and **Add 30 minutes**, in HA 0.5.11 preview. Daily budget has 10-minute increments up to 600 min, Weekly budget has 60-minute increments up to 4200 min, and Weekend bonus adds up to 600 min to the daily allowance separately on Saturday and Sunday. The bonus does **not** increase the independent weekly budget.

**Daily budget remaining** and **Weekly budget remaining** show remaining percentages. **Budget overview (Undo)** (HA 0.13.7+ source) lives under **Controls** on each PC. The dropdown lists daily allowance sources in chronological order, then **∑ TOTAL**, **Gaming Session** (verified daily time used) and the read-only **∑ Remaining Budget**, without divider rows. **∑ TOTAL** remains the always-selected row. All summary rows are read-only; the Gaming Session debit begins with minus as the first character. Whole consumed minutes are rounded up and whole remaining minutes down for display, without changing exact-second accounting; missing usage is explicitly Unknown. Only removable Parent bonuses show a red **⛔** at the end; an authenticated HA administrator can select one to cancel it immediately. The integration refreshes usage and checks the precise grant before removing any minutes. The earlier plain-text Budget overview sensor was retired because its full contents were clipped in the native HA device card; detailed data remains on the Daily budget remaining attributes. **Daily gaming time** and **Weekly gaming time** show explicit `h m s` text. Separate diagnostic **Daily gaming time (minutes)** and **Weekly gaming time (minutes)** sensors remain numeric durations for graphs and automations; since HA 0.13.13 they are **completed integer minutes (floor)**, not rounded decimal minutes. Actual limits still evaluate exact seconds. The existing Direct MQTT **Uptime** diagnostic shows a readable `d h m s` text, with raw seconds in its `uptime_seconds` attribute. Native MQTT **Uptime** gets the same string format only after the Windows 0.4.1 discovery update; the numeric Uptime state changes to text, so numeric automations must use raw attributes instead.

**Parent bonus history and instant administrator-only Undo are available in HA 0.13.7+ source.** Every Add 30 press creates a distinct grant; the native dropdown shows the grant receipt and allows direct cancellation only while the entire grant is untouched. Older releases used separate Prepare/Confirm actions, which no longer exist. See the [Budget Overview walkthrough](features/budget-overview.md#parent-bonus-history-and-undo-ha-090-165).

[Gaming budgets](features/gaming-budgets.md) · [Budget Overview dashboard example](features/budget-overview.md)

## Set allowed gaming hours

On each PC's **Configuration** section, **Schedule enabled** controls both of these native time-picker pairs:

- **Weekday allowed from** / **Weekday allowed until** — Monday through Friday.
- **Weekend allowed from** / **Weekend allowed until** — Saturday and Sunday.

The windows are hours when gaming is **allowed**, not times for an automatic Windows command. For example, 16:00–20:00 permits play until just before 20:00. The end is exclusive, and equal start/end means all-day allowance. Windows can cross midnight: a Sunday 20:00–02:00 window remains valid into Monday until 02:00. Times follow Home Assistant's local timezone, including daylight-saving transitions.

When upgrading from a single-window schedule, the weekend starts out **inheriting the saved weekday window**, so no existing allowance changes unexpectedly. Once a weekend endpoint is edited it becomes independently saved; an unedited weekend endpoint continues to follow its weekday counterpart.

Both **Gaming rules enabled** and **Schedule enabled** must be ON for the passive `schedule` restriction to apply. **Unlimited gaming** overrides it. Scheduling alone never calls Terminate game or Lock PC.

## Native automation actions (HA 0.14.0)

Choose **Developer Tools → Actions → HAL Gaming Control** to call the new integration-owned actions directly, without `button.press`. They take a required HA device-registry ID via the built-in gaming-device selector (one PC only):

- `hal_gaming_control.lock_pc` — lock the selected online PC.
- `hal_gaming_control.terminate_game` — terminate the single freshly verified active HA-tracked game, using the same single-use safety token as the existing manual button.
- `hal_gaming_control.add_bonus` — add a date-scoped Parent bonus with `minutes` (1–600).
- `hal_gaming_control.set_unlimited` — set the current Unlimited override with `enabled: true/false`.
- `hal_gaming_control.popup` — upsert/hide the predefined countdown popup using HA-supplied text, initial seconds, initial bar percentage and up to three response buttons. **Not yet usable on Windows 0.4.1**, which does not advertise popup UI protocol v1; the action fails clearly until compatible Windows code is implemented.

The HA source is **0.14.0 Preview 38**; Windows remains **0.4.1**. No new automated termination behavior or physical deployment. See [action examples](features/parent-actions.md#native-home-assistant-actions-ha-0140-source).

## Lock the PC or close a game

**Lock PC** and **Terminate game** are manual controls. They've worked in limited real-PC tests, but you should test them on your own setup. Closing a game may lose unsaved progress.

Turn on the per-PC **Gaming rules enabled** switch to opt into rule evaluation (default off). This is not an automatic command or installed automation. **Gaming restriction** is a passive per-PC binary sensor in HA 0.5.12. It is `on` when a confirmed budget/schedule/per-game rule is violated, `off` when allowed, and `unavailable` when live accounting is not reliable. Its `reasons` attribute explains why. It **never** sends a command. Since HA 0.13.13 the icon uses valid MDI gamepad variants (filled on restricted, outline when permitted or unavailable), without changing the restriction logic.

**Active game (HA 0.13.9+ source):** The name shows the latest fresh, verified, tracked Windows foreground application, even when the logical console display is OFF. Its icon changes to `mdi:monitor` for ON/DIM and `mdi:monitor-off` for OFF; unknown display falls back to the gamepad icon. This **display-only game name is separate from accounting**: while OFF, gaming seconds still stop increasing and restriction calculations still treat gameplay as idle. If Windows no longer confirms a game, the sensor shows idle/unknown rather than retaining a stale game forever. The existing `display_state` diagnostic attribute continues to expose the trusted screen status.

**Automatic game closing or locking isn't validated or enabled by default.** A parent-authored automation should check both Gaming restriction and Active game, including when a game starts while restriction is already `on`; it should also recheck after HA restart before any action. An unavailable sensor is not evidence of a violation.

[Controls & automations](features/parent-actions.md)

## Preview dashboard and what's next

- **AFK / Screen idle bonus** — included and always enabled on HA 0.13.1+. With fresh verified Windows screen OFF evidence, new gaming time stops counting; the separate daily bonus requires eligible pre-OFF inactivity. HA 0.13.4 fixes hours-old OFF events being misclassified as stale. Physical edge-case validation remains outstanding.
- **Budget Overview** — source preview under [#93](https://github.com/mhalak/hal-gaming-control/issues/93): a read-only per-PC daily/weekly allowance breakdown with a native dashboard stack; installed versions must include the merged change.
- Safe, fully tested automatic restriction enforcement.

[AFK grind](features/screen-idle-bonus.md) · [Budget Overview](features/budget-overview.md)

## Something wrong?

- **Wrong app detected?** Close the editor, focus the right app on Windows, and reopen.
- **New app not saved?** Check the main **Save changes** button.
- **Missing readings?** Check whether the PC and its connection are active. Missing data isn't zero gaming time.
- **Old budget labels after an update?** Restart Home Assistant and refresh the app. Don't delete saved settings just to fix the display.

## Automation-only command execution — 0.5.0 preview

The older preview described how to build a Home Assistant automation that can issue commands. **Nothing closes a game automatically by default**, and a budget sensor is not a safe trigger on its own. Read the [original engineering explanation](reference/ha_integration_technical.md#automation-only-command-execution--050-preview) before testing these ideas.

Need the engineering details, version history or older controls? See the [technical HA reference](reference/ha_integration_technical.md), [known limitations](known_limitations.md) and [release history](ha_releases.md).
