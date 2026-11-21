# Home Assistant setup & everyday use

[← All guides](README.md) · [← Project home](../README.md)

Home Assistant is the family's control panel: see gaming time, choose apps, give extra minutes and use manual controls. It can also handle reminders, which may save the family's last remaining nerve.

**Development preview:** These steps describe HA 0.5.10 preview source. Always check the [release history](ha_releases.md) and the version you've installed.

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

## Set limits & bonuses

Open the PC device page to find **Daily limit**, **Weekly limit** and **Add 30 minutes**, where available in your installed preview.

A bonus adds time **today**, not to the weekly limit.

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
- **Old button labels after an update?** Restart Home Assistant and refresh the app. Don't delete saved settings just to fix the display.

Need the engineering details, version history or older controls? See the [technical HA reference](reference/ha_integration_technical.md), [known limitations](known_limitations.md) and [release history](ha_releases.md).
