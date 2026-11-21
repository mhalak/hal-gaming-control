# Track applications

[← Feature index](../../README.md#feature-tracked-applications) · [All guides](../README.md)

[← Gaming budgets](gaming-budgets.md) · [Controls & automations →](parent-actions.md)

<table>
  <tr>
    <td width="32%" valign="middle">
      <img src="../assets/illustrations/tracked-applications.webp" width="100%" alt="Dad tapping a conceptual Roblox control tablet while daughter plays Roblox, with the friendly HAL robot">
    </td>
    <td valign="middle">
      <h3>The family app detective</h3>
      <p>The computer reports the active app; Home Assistant decides which name appears on the scoreboard. Even <code>javaw.exe</code> deserves an identity check.</p>
    </td>
  </tr>
</table>

The family app detective knows Roblox and Minecraft aren't always called Roblox and Minecraft in Windows. That's why Home Assistant lets you choose names that make sense.

**Development preview:** The app editor exists in HA 0.5.10 preview source. Test real tracking on your own PC.

## Add an app

1. Open the app on your child's PC and bring it to the front.
2. In Home Assistant, open **Settings → Devices & services → SmartHouse Parental Control**, then select the PC.
3. Choose **Configure → Tracked applications** and check **Currently detected application**.
4. Under **Application List**, press **Add**, enter a friendly name and confirm the small dialog.
5. **Press Save changes in the main window too.** The first Add only changes the draft list.
6. Reopen the editor to check that your name was saved.

**On a phone:** The keyboard's Enter key won't submit the small dialog. Tap **Add** and then the main **Save changes** button.

## What can it track?

Any supported foreground app, not just games. For example, `RobloxPlayerBeta.exe` can display as **Roblox**.

Some Java apps need more information to tell Minecraft from other apps using `javaw.exe`. When the system can't identify an app safely, it should say so rather than guess.

**App names and tracking choices stay in Home Assistant**, not on the child's PC.

## Something look wrong?

- **Wrong app shown?** Close the editor, focus the right app on Windows and reopen it.
- **App disappeared?** Check the main **Save changes** button.
- **Not tracked** means the app isn't in this PC's list. **Idle** and **Unavailable** mean different things.
- Tracking an app does **not** automatically close it.

*Dad's Roblox slider is part of the cartoon, not a real control screen. Nice try, Dad.*

**For developers:** [Original technical notes](../reference/features/tracked-applications-preview-notes.md).

---

**Explore more features:** [← Gaming budgets](gaming-budgets.md) · [Controls & automations →](parent-actions.md)
