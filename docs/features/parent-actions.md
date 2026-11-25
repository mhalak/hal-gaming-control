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
      <p>Every family needs a scapegoat. Ours runs on Home Assistant. No feelings, no parental guilt, and zero weakness for puppy eyes.</p>
    </td>
  </tr>
</table>

There's just one tiny problem: our server has never passed its **Flying Objects Resistance Test**. Game controllers, cushions, and the occasional airborne slipper remain dangerously outside its warranty coverage.

The beauty of **Home Assistant automations**? Parents make the rules, choose the reminders, and decide how generous the grace periods should be. The house handles the countdown, the robot handles the complaints, and Dad can finally say:

**“Don't look at me. I just live here, same as you.”**

**Development preview (HA 0.7.2):** **Gaming restriction** is a passive per-PC rule signal. **Lock PC** and legacy **Terminate game** worked in limited real-PC tests. The new **Terminate active game** path still requires a real-PC pilot. **Automatic enforcement is not yet validated or enabled by default.**

## Native Home Assistant actions (HA 0.14.0 source)

These are **registered custom integration actions** in **Developer Tools → Actions**, scripts and automations. They do **not** call `button.press` internally and they use the existing device-specific safety/policy logic. Select **one HAL Gaming Control device** in the action's `device_id` field. In YAML, use its **Home Assistant device-registry ID** (the long ID from the device page), not the Windows hostname or an entity ID. There is no default device and no broadcast.

```yaml
actions:
  - action: hal_gaming_control.lock_pc
    data:
      device_id: REPLACE_WITH_HA_DEVICE_REGISTRY_ID
  - action: hal_gaming_control.terminate_game
    data:
      device_id: REPLACE_WITH_HA_DEVICE_REGISTRY_ID
```

`terminate_game` means **terminate the freshly verified foreground HA-tracked application**, not arbitrary software. Windows must supply a short-lived one-use terminate offer; repeated calls cannot reuse that offer. `lock_pc` requires fresh PC telemetry and an advertised lock capability. MQTT publish is not a confirmed Windows execution acknowledgement.

HA-only actions: `hal_gaming_control.add_bonus` with `minutes: 15` (1–600, Smart Parent Bonus; requires verified effective accounting) and `hal_gaming_control.set_unlimited` with `enabled: true` or `false` (also works offline).

The generic `hal_gaming_control.popup` action will **upsert** or **hide** a predefined PC popup with an initial `remaining_seconds`, `progress_percent`, HA text and 0–3 response buttons. It requires a Windows agent advertising popup UI protocol v1. **Windows agent 0.4.1 does not implement the renderer**, so the current HA action deliberately fails rather than pretending a popup appeared. The full Windows implementation/response channel remains tracked in [#8](https://github.com/mhalak/hal-gaming-control/issues/8). Example configuration for a future compatible agent:

```yaml
action: hal_gaming_control.popup
data:
  device_id: REPLACE_WITH_HA_DEVICE_REGISTRY_ID
  operation: upsert
  heading: Gaming time remaining
  description: Weekly budget
  remaining_seconds: 598
  progress_percent: 24
  buttons:
    - id: ok
      text: OK
      color: neutral
    - id: request_more
      text: Request more time
      color: primary
```

The response button ID is a future HA-side event, **never** direct permission to grant time or execute a Windows command. Closing the game can lose unsaved progress. These actions are restricted to HA admins; no automatic enforcement is enabled by installation.

## Smart warning automation (#243 source preview)

In the automation editor choose the **Gaming budget reached threshold** trigger, enter 10 minutes and select the gaming PCs (or leave the list empty for any PC). Choose the **Display gaming popup** action, set Countdown source and Progress source to Automatic, and optionally choose Automatic for Detail source. Use the triggering HA registry device ID via the action's YAML editor; a template-free dynamic target selector is not established.

```yaml
alias: Gaming time warning
triggers:
  - trigger: hal_gaming_control.remaining_budget_reached
    options:
      minutes: 10
actions:
  - action: hal_gaming_control.popup
    data:
      device_id: "{{ trigger.device_id }}"
      operation: upsert
      heading: Gaming time remaining
      countdown_mode: automatic
      progress_mode: automatic
      description_mode: automatic
mode: parallel
```

The trigger fires on a verified downward crossing, not on startup or recovery from unknown. A bonus that raises the remaining allowance above the threshold rearms it. Use a separate zero-minute trigger if wanted. The initial progress is remaining / (verified used + remaining) from the selected budget period. With popup protocol v1 Windows animates the initial values locally; this is not an authoritative live countdown if gaming pauses or a parent grants more time. Independently hidden fields and safe live resynchronization require the separate cross-component extension. No automatic warning, lock or terminate automation is installed. Test on the actual PC with a compatible agent before use.

## Use a manual control

1. Open the **correct child's PC** in Home Assistant.
2. Make sure it is connected and sending recent data.
3. Choose an action:

   - **Lock PC:** Locks Windows. The child can unlock it normally; the game may keep running.
   - **Terminate active game (Windows 0.2.9 + HA 0.7.2):** Targets one currently foreground, HA-tracked application using a short-lived verified Windows capability. If the PC is idle, offline, untracked or its foreground changed, the control is unavailable. It never accepts an arbitrary process name or PID from HA. **Unsaved progress may be lost.**
   - **Terminate game (legacy):** On PCs retaining a local `games` allowlist, closes configured matching processes. This legacy button may remain unavailable after moving to the new catalog-free mode; use the new active-game control instead.

Adding a game to the tracked list never closes it by itself. The new manual targeted control is not an automation or a silent enforcement engine: a parent explicitly presses the button, then Windows performs another identity/focus check before killing exactly one process. A successful MQTT publish is not proof of termination. Keep the child's unsaved progress in mind.

## Gaming restriction sensor

The per-PC **Gaming restriction** binary sensor exposes the result of the verified budget/schedule rules. `on` means the child has crossed at least one applicable limit; `off` means none apply; `unavailable` means HA cannot establish the truth from reliable live accounting. Its attributes include `reasons` and `reason`, such as `daily`, `weekly`, `schedule` or `game:Roblox`.

**Gaming rules enabled** is a separate HA switch, initially **off**. Turn it on for the selected PC when you want the restriction sensor to evaluate active rules; it does not itself terminate anything. **Unlimited gaming** can still override the rules.

The sensor is **passive** and never shuts down a game. A future parent-authored automation should react to either (1) Gaming restriction changing to `on` **or** (2) Active game changing from idle to a game while restriction is already `on`. Also recheck actual state on HA startup; use a warning/grace period and recheck before a destructive command. Never send a command solely because the sensor becomes unavailable.

## Weekday and weekend gaming schedule

Each PC's **Configuration** section has four native HA time pickers: **Weekday allowed from/until** (Monday–Friday) and **Weekend allowed from/until** (Saturday–Sunday). The shared **Schedule enabled** switch turns time-window restrictions on or off, while **Gaming rules enabled** must also be on for the passive `schedule` reason to apply. **Unlimited gaming** bypasses it.

Windows specify permitted playing hours, not times to close games. An overnight window is tied to its start day: Friday night can finish on Saturday morning, and Sunday night can finish on Monday morning. Endpoints are end-exclusive, and equal start/end permits all day for that start day. Home Assistant uses its local time.

Existing saved weekday hours continue unchanged. Until a weekend endpoint is explicitly set, it inherits its weekday equivalent; once saved, the weekend option is independent. No schedule edit automatically sends a Windows command.

## Why Home Assistant automations?

This is the fun part: set your own rules. You might send a reminder, allow a short grace period or ask a parent to step in — instead of repeating “five more minutes” all evening.

A future safe workflow could warn the child, wait a moment and check whether the restriction still applies before taking action.

**Keep automatic game closing and locking off for now.** The restriction signal exists, but an end-to-end safe automation workflow and physical testing are still pending. Missing or outdated data is not proof of a broken rule.

The robot insists on a trial run before meeting angry children.

**For developers:** [Original technical notes](../reference/features/parent-actions-preview-notes.md).

More: [Gaming budgets](gaming-budgets.md) · [Known limitations](../known_limitations.md)

---

**Explore more features:** [← Track applications](tracked-applications.md) · [AFK grind →](screen-idle-bonus.md)
