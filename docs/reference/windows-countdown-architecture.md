# HA-driven Windows gaming popup architecture (#8)

[← Engineering guides](../README.md) · [Parent actions](../features/parent-actions.md) · [Issue #8](https://github.com/mhalak/hal-gaming-control/issues/8)

> **Architecture proposal only.** This document does not introduce working popup functionality, new MQTT subscriptions, Windows binaries, released versions or deployment permissions. `#56` deployment HOLD is unchanged.

## Binding owner decision

**Home Assistant owns 100% of popup behavior and gaming policy.** The Windows service is a **presentation transport**, not a second gaming-policy engine. The Windows interactive-session helper is a **renderer**. Do not calculate budgets, deadlines, bonuses, schedule windows, per-game limits, warning thresholds, colors, progress percentages or which popup to display on Windows.

The only Windows-local decisions are operational safeguards: validate a device-scoped incoming message, reject stale/malformed/replayed input, ensure the helper is in the correct unlocked interactive session, render the supplied view, hide a stale window, and report a local dismissal. These safeguards must **never** grant time, change a policy, issue a termination/lock or synthesize a countdown.

## Component responsibilities

| Component | Must do | Must not do |
| --- | --- | --- |
| HA popup controller | Compute authoritative eligibility, limiting reason, time remaining, warnings, rearming, severity, progress, copy, and when to show/update/hide. Own dismissal history and recompute on options/telemetry/time changes. | Send automatic Lock PC / Terminate game merely because a warning is due; trust old/unknown gaming time as zero. |
| MQTT UI channel | Carry short-lived, **HA→Windows** versioned display instructions for the exact Windows hostname, plus optional **Windows→HA** delivery/dismissal events. | Reuse or extend the single Unified MQTT v3 **monitoring** packet; retain popups; transport HTML, scripts, Windows commands, credentials or arbitrary executable targets. |
| Windows SYSTEM service | Authenticate/validate/deduplicate the display instruction, route it to the verified active-session helper, forward dismissal events, stop delivery on disconnect/session changes. | Calculate remaining seconds, alter a view, choose a threshold, infer a new popup, or display on Session 0. |
| Windows unelevated popup helper | Render exactly the HA-supplied title, text, time string, severity, progress, footer; show/update/hide a **single** nonmodal window; close on user X and report dismissal. | Subscribe directly to MQTT, evaluate gaming rules, decrement timers or change policy, grant bonuses, kill/lock processes or run arbitrary actions. |

### Runtime flow

```text
Windows v3 telemetry ──────────────────────────────→ Home Assistant
                                                       ├─ existing foreground and policy accounting
                                                       ├─ popup scheduler / state machine
                                                       └─ AUTHORITATIVE view (show / update / hide)
                                                             │
                                                    local MQTT broker
                                                   ui/popup (non-retained)
                                                             │
                                                Windows service (SYSTEM)
                                                validation + IPC transport
                                                             │
                                               separate protected named pipe
                                                             │
                                                unelevated popup helper
                                                Windows interactive desktop
                                                             │
                                     optional dismiss event ──┴─→ HA popup controller
```

The current `--focus-helper` and its outbound-only security pipe remain independent. A separate `--popup-helper` mode in the **same packaged Windows agent** can use `CreateProcessAsUser`, the existing active/unlocked-session selection, and a protected, PID-verified pipe. No second Windows service or cloud service is required. No change to the existing mandatory Unified MQTT v3 telemetry schema.

## Proposed wire contract (popup UI v1; independent of monitoring v3)

**HA publishes:** `SmartHouse/Gaming/<device_id>/ui/popup`.

**Agent can report:** `SmartHouse/Gaming/<device_id>/ui/popup_event`.

No retained messages. UI topic access is explicitly scoped in broker ACLs: HA-only publisher for `ui/popup`, matching Windows agent as subscriber, inverse for the optional event channel. No wildcard topic privileges are introduced by the feature.

Example HA **show** command (illustrative contract, not yet deployed):

```json
{
  "version": 1,
  "device_id": "DESKTOP-EXAMPLE",
  "producer_epoch": "0123456789abcdef0123456789abcdef",
  "sequence": 41,
  "issued_at": 1795000000,
  "ttl_seconds": 15,
  "popup_id": "f2c8e1d4-6e93-4e6b-aaf7-5e3517eea701",
  "operation": "show",
  "view": {
    "title": "HAL Gaming Control",
    "heading": "Gaming time remaining",
    "time_text": "09:58",
    "description": "Weekly budget",
    "severity": "danger",
    "progress_percent": 24,
    "footer": "Powered by HAL Systems"
  }
}
```

- `operation` is an **allowlisted enum**: `show`, `update`, `hide`. An `update` changes the current `popup_id` view only; a `hide` closes it. A new `popup_id` represents a new HA-authorized warning episode. The renderer never invents an episode.
- **All displayed strings, even `time_text`, come from HA.** Windows must not parse `09:58` to decrement it, determine a new color from a time threshold, or infer a budget. Progress bar width is exactly the HA-provided bounded percentage; Windows only draws it.
- `show`/`update` carry `view`; `hide` has no view. All identifiers, strings and numeric bounds require strict allowlisted validation (e.g. finite percentage 0–100; bounded title/text/footer lengths; severity `info|warning|danger`; fixed known message size). No HTML/Markdown/web links/scripts/paths/arbitrary buttons are interpreted.
- Accept only expected device ID, non-retained messages with a valid sequence within its producer epoch and bounded `issued_at`/TTL. Duplicate, stale, mismatched or invalid messages are ignored. On reconnect/HA restart, reject old sequence/epoch replay and require a fresh HA command. Message delivery does not authorize an arbitrary Windows action.
- Prefer non-retained QoS 1 for state changes (`show`/`hide`) and bounded periodic `update` snapshots for loss recovery. **At-least-once delivery requires idempotence**; never let a duplicate `show` reopen an already dismissed episode.
- HA owns liveness: publish refreshed desired views while a popup should remain visible; the Windows service/helper **hides on TTL expiry or connection/session loss**. This local timeout is only a safety guard against stale display; it is not a budget countdown.
- HA can send the formatted number every 1 second in the final minute and at a slower cadence earlier (e.g. 5 seconds while shown). This meets the *HA sends everything* rule: **there is no autonomous ticking clock on Windows.** Limit cadence to visible/populated views; evaluate actual HA runtime cost in tests.
- A user closing the window produces only a bounded `dismissed` event with `device_id`, `popup_id`, a unique event ID and timestamp (same private pipe/verified session). HA owns durable suppression and whether a later threshold may reopen. This event **cannot** grant a bonus or issue a privileged command. A temporarily disconnected UI may locally suppress duplicates for that same ID but must never create a new warning.
- To avoid a new message from HA waking a dismissed popup merely because of a retransmission, HA persists the episode's dismissal state. Do not use user-facing text or computed seconds as a deduplication key.

## HA-only popup state machine

```text
No warning
  ├─ fresh verified gaming + eligible 60/10/1/0 threshold → SHOW(new id)
  ├─ unreliable/disabled/unlimited → no warning
  └─ policy reset / bonus → recalculate (no stale time)
Shown(id)
  ├─ fresh authoritative view changed → UPDATE(same id)
  ├─ new HA-authorized threshold → SHOW(new id)
  ├─ parent policy changes / unknown → HIDE(id) or replace with new HA view
  ├─ child closes → record dismissed(id); HIDE(id)
  └─ stale HA or MQTT → Windows hides on TTL (safety only)
Dismissed(id)
  ├─ repeated message for id → ignored
  └─ next eligible warning episode/new id → SHOW
```

HA derives the **most restrictive applicable reason** from validated daily, weekly and per-app remaining seconds, allowed schedule window and state of rules, Screen Idle/Parent/Weekend bonuses, Unlimited, and local date/week rollover. The selected reason and matching denominator drive the progress label. The exact policy for equal-time ties, skipped thresholds, bonus rearm, schedule boundaries and midnight/DST belongs in HA tests. Do not use the existing percentage-only budget sensors to reverse-engineer a precise countdown.

**Zero warning** is still HA-owned: HA may keep the zero episode visible after the game exits, subject to dismissal and freshness updates. The Windows popup does not decide that game exit means hide. A separate parent-approved HA automation or manual button is still required to end/lock a game.

## Windows lifecycle / security

- Only a verified **unlocked** Windows interactive user session may host the popup; never Session 0. Use the existing Windows token and session-selection primitives to spawn **one** unelevated `--popup-helper`, separate from the foreground helper.
- Establish a new dedicated SDDL-constrained named pipe. Verify helper PID, process identity and session; authenticate each end, bound payloads, and never accept arbitrary pipe names, local executable paths or window handles from MQTT.
- A session switch, lock, logoff, helper crash, service restart, broker disconnect or TTL expiry closes or hides old UI. New UI requires fresh HA state; nothing is replayed from retained MQTT.
- Native pywin32 rendering is adequate for a nonmodal, dismissible window, left-anchored shrinking bar, colored status plus text accessibility, and `Powered by HAL Systems`. No focus theft on every update. Do not promise visibility over exclusive-fullscreen games or anti-cheat overlays.
- A generic UI renderer still needs a **strict command allowlist**: no HTML/JS, arbitrary image/URL load, buttons that invoke OS commands, file paths, privilege escalation or dynamic shell execution.

## Incremental implementation boundaries

1. **HA projection + protocol:** define strict JSON schema/contract fixture and HA-owned warning state machine, including all budget and schedule scenarios; unit tests for thresholds, stale data, two PCs, bonus/rearming, unlimited, midnight and DST.
2. **Transport only:** HA publishes commands; Windows MQTT subscriber validates them and forwards through a new private pipe. Unit tests for QoS/retain/replay/ordering/TTL/device/identity and locked or switched sessions. **No visible popup yet.**
3. **Pure renderer:** interactive-session `--popup-helper` draws only HA-supplied fields and emits optional dismissal event. Test one instance, show/update/hide, no focus stealing, stale hide, errors and fullscreen limitations.
4. **Real-PC acceptance:** supervised Windows 10/11 pilot with Roblox/Minecraft in windowed/borderless/fullscreen; service-as-SYSTEM, screen off/lock, HA reboot, MQTT outage, parent bonus, Reset/Unlimited, and duplicate warning suppression.

Out of scope for #8: Windows-owned gaming-budget math, remote enforcement, a new monitoring version, Android companion, parental approval buttons, and **#163 Request more time**. Future #163 may add a strictly bounded child-request event to HA; only HA can approve and grant.

**Version/deploy discipline:** changes to the actual HA and Windows distributables require independently incremented versions and successful CI. This architecture document alone does not change component versions, publish a release or lift issue #56's deployment HOLD.
