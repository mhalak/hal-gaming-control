# HA-driven Windows countdown popup — fixed form contract (#8)

[← Developer guides](../README.md) · [GitHub issue #8](https://github.com/mhalak/hal-gaming-control/issues/8) · [Interactive design mock](countdown-popup-preview.html)

> **Owner decision, 2026-11-24: this revision supersedes the earlier architecture draft.**
> Documentation and prototype only; no Windows service, Home Assistant runtime, MQTT deployment, agent release or change to #56 deployment HOLD is implied.

## Main principle

**Home Assistant is the only source of gaming policy and popup content.** Windows gets a predefined, fixed-layout **presentation form** with data to display. There is no Windows budget calculation, schedule logic, threshold selection, bonus authorization, or automatic enforcement.

Unlike the first proposal, Windows **does advance the visible countdown locally** from an initial number of seconds supplied by HA; this is presentation interpolation, **not** new gaming-time accounting. The bar can similarly shrink between HA updates. Windows has a **hardcoded visual bar color palette**. HA chooses each response button's label and named color. HA remains free to send new data any time and to show or hide the popup.

| Responsibility | Home Assistant | Windows |
| --- | --- | --- |
| Daily, weekly, per-game budgets, schedule, bonuses, Unlimited | Calculate and authorize | Never calculate or modify |
| When to show, update or hide a popup, warning episodes | Decide and send command | Follow command |
| Title, message, initial countdown seconds, starting bar percentage | Supply data | Render exactly the data |
| Countdown animation | Set initial/re-sync anchor | Visually subtract elapsed monotonic time down to 0 |
| Progress bar | Supply starting percent | Draw and smoothly interpolate remaining width |
| Bar color | Does not need to send | Fixed green/amber/red UI palette (cosmetic only) |
| Response buttons | Define 0–3 button IDs, labels, named colors; handle response | Render equally sized buttons and return chosen ID |
| Closing/reopening | May send new command any time | X closes; next *new valid* upsert opens it again |
| Safety | HA policy evidence, authenticated MQTT, periodic desired state | Validate sender/topic/device/order/freshness, hide on stale or session change |

## Fixed popup form

The layout **never changes into arbitrary remote HTML**. It has a constant header with HAL logo/name and X; an HA text heading; a large centered time; a horizontally left-anchored progress bar; one concise HA detail line (e.g. `Weekly budget`); an optional equal-width button row; and the fixed `Powered by HAL Systems` footer. All text is plain and bounded.

Native pywin32 or equivalent Win32 drawing in an unelevated interactive user process is preferred. The SYSTEM Windows service does not create windows on Session 0. One popup window per active unlocked session/device. No auto-focus theft or recurring modal dialogs.

**Buttons:** 0 buttons → no row, 1 button → full row, 2 buttons → two equal halves, 3 buttons → three equal thirds, with small consistent gaps. Reconfiguration of button count while open must resize the same popup without closing it. Text and button color choice come from HA, constrained to `neutral|primary|success|warning|danger` (no arbitrary hex CSS, HTML, scripts, links or shell commands). The bar's background and traffic-light colors are entirely hardcoded in the renderer.

**Illustrative look:** centered `09:58`, a 24%-wide red remaining-time bar, `Weekly budget` under it, 2 side-by-side responses `OK` / `Request more time`. [Open the browser-only interactive preview](countdown-popup-preview.html). The preview is not a running Windows agent; it uses synthetic messages.

## Runtime topology (Unified MQTT v3 unaffected)

```text
    Windows Unified MQTT v3 telemetry ──→ HA foreground and policy
                                                │
                                    HA popup controller
                           warning/bonus/threshold/UX decision
                                                │
                      non-retained HA→Windows MQTT ui/popup
                                                │
                             SYSTEM service (validate + relay)
                                                │
                         protected, PID-checked separate named pipe
                                                │
                       unelevated --popup-helper in active user session
                               fixed form + local live interpolation
                                                │
                     optional button/X event → service → MQTT → HA
```

- Existing Windows `--focus-helper` / one-way named pipe remain intact. Reuse the supported `CreateProcessAsUser`/session selection primitives but establish a **separate** SDDL-constrained, authenticated helper channel.
- No second Windows service or new cloud dependency. The existing one-directory agent package can include the popup helper mode and native UI resources.
- HA publishes only to `SmartHouse/Gaming/<device_id>/ui/popup`; optional Windows feedback uses `SmartHouse/Gaming/<device_id>/ui/popup_event`.
- Scope broker ACLs by exact device and direction. This is a **separate UI/control channel**, not a new publisher or compatibility mode for the strict `state/telemetry` Unified v3 monitoring snapshot.

## Proposed popup UI v1 packet

A **new valid upsert is always a show-or-update**: if the window is already displayed, update in place; if closed, reopen. No split `show` and `update` semantics are needed.

```json
{
  "version": 1,
  "device_id": "DESKTOP-EXAMPLE",
  "producer_epoch": "0123456789abcdef0123456789abcdef",
  "sequence": 41,
  "issued_at": 1795000000,
  "message_ttl_seconds": 15,
  "display_stale_after_seconds": 120,
  "popup_id": "f2c8e1d4-6e93-4e6b-aaf7-5e3517eea701",
  "operation": "upsert",
  "view": {
    "heading": "Gaming time remaining",
    "remaining_seconds": 598,
    "description": "Weekly budget",
    "progress_percent": 24,
    "buttons": [
      {"id": "dismiss", "text": "OK", "color": "neutral"},
      {"id": "request_more", "text": "Request more time", "color": "primary"}
    ]
  }
}
```

The header **HAL Gaming Control** and footer **Powered by HAL Systems** are part of the fixed form. An optional `view.message` plain-text subheading can be added once needed, but no markup or dynamic page layout is allowed. `operation: "hide"` closes the current view (matching the popup ID or a HA-authorized all-views hide for this specific device).

### Live local countdown and bar

1. On accepted `upsert`, record `remaining_seconds = N`, `progress_percent = P` and the **local monotonic reception time** `t0`. Render the time as `MM:SS` (or `H:MM:SS` above an hour).
2. On each local visual tick, `remaining_display = max(0, N - elapsed_monotonic)`; format and repaint. **Windows does not publish these interpolated values back as usage data.** At zero, show `00:00` until HA hides/replaces the popup; never lock/terminate a game.
3. Keep the progress bar smooth using a purely visual interpolation: `width = (N > 0 ? P * remaining_display / N : 0)`, clamped 0–100. A new HA `upsert` resets both anchors to the **new authoritative** seconds and percent. No extra total-budget metadata is required for this first design.
4. Hardcoded **visual** bar colors: green for >30 minutes, amber for >10 through 30 minutes, red for ≤10 minutes (including zero); text must still communicate the restriction. The *decision to display* a 60/10/1/0 warning remains HA-only.
5. Local interpolation cannot know HA bonuses, schedule changes or stopped gameplay. HA should send a fresh snapshot promptly for relevant state changes and periodically while the popup is displayed. When disconnected too long, the service **hides** stale UI instead of guessing a new allowance. The countdown is advisory, not an exact enforcement clock.

### Dynamic responses

- Up to 3 button descriptors; `buttons: []` produces no response row. Every button has a bounded unique `id`, text and palette enum. Button count automatically divides row width 1/2/3 without custom layout commands.
- Clicking a button emits an **observation** (not an action grant), e.g. `{"version":1,"device_id":"DESKTOP-EXAMPLE","popup_id":"f2c8e1d4-6e93-4e6b-aaf7-5e3517eea701","event_id":"...","kind":"button","button_id":"request_more"}` on the optional response topic. X emits `kind:"closed"`.
- The service verifies that the popup ID and button ID belong to the current accepted view in that same user session; HA revalidates device, freshness, ID and parent policy before deciding anything. A response **never** directly grants time or executes a Windows command. The upcoming #163 request-more-time flow can reuse this generic event mechanism.
- **New upsert while window open:** replace heading, countdown, bar and entire button row in place. **New valid upsert after X/hidden:** open again, even for the same `popup_id`. Repeated MQTT *delivery* of the same epoch+sequence is dropped; a genuinely new HA command with a newer sequence may reopen.
- If HA repeatedly sends newer upserts after a child closes a window, that window will repeatedly reopen. That is explicitly **HA's responsibility** to suppress/cool down if desired. The renderer must not impose its own warning or dismissal policy.

## Security, freshness and lifecycle

- Require strict numeric/string bounds, enum allowlists, unique button IDs, max message bytes, validated `device_id`, no retained MQTT packets, short expiry, per-HA producer epoch/sequence ordering and prompt rejection of malformed or replayed input.
- `message_ttl_seconds` limits **acceptance of an incoming message**; `display_stale_after_seconds` separately limits how long a previously displayed popup can remain active without fresh HA state. Use monotonic time after acceptance. Losing broker connectivity, locked/logged-off/changed session, helper death or service restart hides the popup; never resurrect old retained data.
- The helper runs unelevated under the verified interactive user token, not SYSTEM. Dedicated access-controlled named pipe, PID and session verification, bounded payloads and single instance. Do not interpret any MQTT-provided string as executable command, filename, module, URL or window handle.
- No arbitrary process kill, lock PC, budget change, signing bypass, installation, persistent remote code, or Windows 0.4.x/v3 monitoring change from these UI messages.
- Accessibility: fixed concise heading and time, legible contrast, descriptive text alongside color, keyboard accessibility, equal hit areas, screen-reader labels where Windows UI toolkit permits, and no focus stealing on each update. Exclusive fullscreen/anti-cheat overlay behavior is **not guaranteed**.

## Delivery slices and acceptance

1. **HA policy projection + v1 JSON fixture:** determine selected limiting reason, remaining seconds, starting percent and response buttons (no local Windows policy), plus show/hide/warning scheduling. Test exact-second limits, daily/weekly/per-game schedules, bonuses, Unlimited, reset, offline, DST/midnight, multiple PCs and state transitions.
2. **Windows MQTT subscription + private IPC:** validate and forward only, authenticate correct user session, report response IDs; tests for retain/expiry/replay/ordering and wrong device. No actual visible UI in this slice.
3. **Fixed GUI renderer:** native Windows window from supplied mock packets, local live monotonic countdown, shrinking bar/hardcoded colors, 0/1/2/3 buttons, equal width, in-place upsert, X→reopen, hide, unknown/disconnect and no focus stealing.
4. **Physical Windows pilot:** service under LocalSystem, interactive Windows accounts, Roblox/Minecraft fullscreen/borderless, lock/unlock, HA reboot, MQTT loss, bonus/Unlimited, screen OFF, buttons and real reconnect recovery. Full live rollout remains gated by #56.

Outside #8: automatic enforcement, Android, Windows-owned budgets, full request-more-time approval flow (#163), Unified MQTT monitoring v4, custom arbitrary markup and automatic installs. Runtime HA/Windows changes require their own version increments and green CI.
