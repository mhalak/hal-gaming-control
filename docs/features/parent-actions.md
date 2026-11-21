# Controls & automations

[← Back to features](../../README.md#feature-parent-actions) · [All guides](../README.md)

<table>
  <tr>
    <td width="132" valign="middle">
      <img src="../assets/illustrations/parent-actions.webp" width="120" alt="Dad pushing a resisting HAL robot toward angry children while mum watches, under an Automation Rules sign">
    </td>
    <td valign="middle">
      <h3>Automation Rules!</h3>
      <p>The house can help enforce rules; the robot would rather not negotiate with the kids. Manual buttons work in preview, while safe automatic enforcement still requires validation.</p>
    </td>
  </tr>
</table>

**Automation Rules!** Dad wants the robot to handle the arguments. The robot would like to file a complaint.

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

[Gaming budgets](gaming-budgets.md) · [Known limitations](../known_limitations.md)
