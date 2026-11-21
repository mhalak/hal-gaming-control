# Home Assistant setup & everyday use

[← All guides](README.md) · [← Project home](../README.md)

Home Assistant is the family's control panel: see gaming time, choose apps, give extra minutes and use manual controls. It can also handle reminders, which may save the family's last remaining nerve.

**Development preview:** These steps describe HA 0.5.11 preview source. Always check the [release history](ha_releases.md) and the version you've installed.

## Set it up

1. Install the integration from source or HACS, **where available**, then restart Home Assistant.
2. Make sure **MQTT** and **Recorder** are enabled.
3. Set up the [Windows companion](windows_deployment.md) on one test PC.
4. Add or select that PC in Home Assistant. Check that **fresh readings** appear.
5. Leave automatic restrictions off until you've tested the setup.

**HACS installs only the Home Assistant part.** It can't install the Windows program on your child's PC.

## Track an app

Open **Settings → Devices & services → SmartHouse Parental Control**, choose the PC and select **Configure → Tracked applications**.

Home Assistant shows the app detected when the editor opened. It's a **snapshot**, not a live display. If the child switches apps, close and reopen the editor to see the new one.

To save an app, confirm the small **Add** dialog, then press **Save changes** in the main window too. Yes, two buttons. The robot is lobbying for fewer.

[See the app guide](features/tracked-applications.md).

## Set budgets & bonuses

Open the PC device page to find **Daily budget**, **Weekly budget**, **Weekend bonus** and **Add 30 minutes**, in HA 0.5.11 preview. Daily budget has 10-minute increments up to 600 min, Weekly budget has 60-minute increments up to 4200 min, and Weekend bonus adds up to 600 min to the daily allowance separately on Saturday and Sunday. The bonus does **not** increase the independent weekly budget.\n\n**Daily budget remaining** and **Weekly budget remaining** show remaining percentages. **Daily gaming time** and **Weekly gaming time** use duration readings displayed as hours, minutes and seconds by Home Assistant.

[Gaming budgets](features/gaming-budgets.md)

## Lock the PC or close a game

**Lock PC** and **Terminate game** are manual controls. They've worked in limited real-PC tests, but you should test them on your own setup. Closing a game may lose unsaved progress.

**Automatic game closing or locking isn't validated or enabled by default.** A budget sensor alone isn't permission to terminate a game.

[Controls & automations](features/parent-actions.md)

## Not available yet

- **AFK / Screen idle bonus** — future screen-off tracking and daily bonuses.
- **Budget Overview** — a simple breakdown of allowances, bonuses and time used.
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
