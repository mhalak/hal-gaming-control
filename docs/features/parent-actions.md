# Controls & automations

[← Feature index](../../README.md#feature-parent-actions) · [All guides](../README.md)

[← Track applications](tracked-applications.md) · [AFK grind →](screen-idle-bonus.md)

<table>
  <tr>
    <td width="32%" valign="middle">
      <img src="../assets/illustrations/parent-actions.webp" width="100%" alt="Dad pushing a resisting HAL robot toward angry children while mum watches, under an Automation Rules sign">
    </td>
    <td valign="middle">
      <h3>Automation Rules!</h3>
      <p>Every family needs a scapegoat. Ours runs on Home Assistant. Unlike Dad, the smart home has no feelings to hurt, so saying <strong>“No”</strong> to “just five more minutes” is much easier. Naturally, Dad sends the robot to deliver the news.</p>
      <p>There's just one small problem: our server has yet to pass its <strong>Flying Objects Resistance Test</strong>. Controllers, cushions, and the occasional airborne slipper remain untested.</p>
      <p>That's the beauty of <strong>Home Assistant automations</strong>: parents set the rules, reminders, and grace periods; the house gets to say <strong>“Time's up!”</strong> with absolutely no fear of the inevitable “But Daaad!” Dad can handle the appeals. The robot, unfortunately, runs the complaints department.</p>
    </td>
  </tr>
</table>

The point isn't to take parents out of the loop. Let Home Assistant handle the repeated reminders while you decide what happens next.

**Development preview:** **Lock PC** and **Terminate game** worked in limited real-PC tests. **Automatic enforcement is not yet validated or enabled by default.**

## Use a manual control

1. Open the **correct child's PC** in Home Assistant.
2. Make sure it is connected and sending recent data.
3. Choose an action:

   - **Lock PC:** Locks Windows. The child can unlock it normally; the game may keep running.
   - **Terminate game:** Closes configured matching game processes. **Unsaved progress may be lost.**

Adding a game to the tracked list never closes it by itself.

## Why Home Assistant automations?

This is the fun part: set your own rules. You might send a reminder, allow a short grace period or ask a parent to step in — instead of repeating “five more minutes” all evening.

A future safe workflow could warn the child, wait a moment and check whether the restriction still applies before taking action.

**Keep automatic game closing and locking off for now.** The restriction trigger and full workflow need testing. Missing or outdated data is not proof of a broken rule.

The robot insists on a trial run before meeting angry children.

**For developers:** [Original technical notes](../reference/features/parent-actions-preview-notes.md).

More: [Gaming budgets](gaming-budgets.md) · [Known limitations](../known_limitations.md)

---

**Explore more features:** [← Track applications](tracked-applications.md) · [AFK grind →](screen-idle-bonus.md)
