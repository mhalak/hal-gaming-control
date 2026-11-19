# Product direction — SmartHouse Parental Control

Powered by HAL Systems.

This document records agreed product behavior, not a claim that each feature is already released. See the [release history](ha_releases.md) and [HA guide](ha_integration.md) for version-specific behavior.

## Delivery roadmap

| Feature | Scope | Status |
| --- | --- | --- |
| Budget model | Daily and weekly time sensors, Weekend bonus, automation-owned enforcement | Planned 0.5.0; not included in this snapshot |
| Foreground accounting | Foreground telemetry and foreground-only accounting | Priority follow-up; required before accurate active application accounting |
| Application list | Application list and enrollment from live foreground identity | Backlog improvement |
| Countdown popup | Child-facing Windows countdown and warning popup | Backlog improvement; visual behavior agreed |
| Future | Optional request for five more minutes | Deferred until popup UX is validated |

Keep restrictions disabled during development smoke tests; stable releases and trusted binary distribution require validation.

## Budget model (HA 0.5.0 candidate)

Only two independent quotas: **Daily limit** and **Weekly limit**. **Weekend bonus** is an additive allowance, not a third quota or a replacement daily budget. The bonus applies separately on Saturday and Sunday, using HA's local calendar. Unused bonus does not roll over.

Effective finite daily allowance = Daily limit + applicable Weekend bonus + today's one-off bonus (Add 30 minutes). The weekly cap is independent and neither bonus increases it. The daily limit remains unlimited when disabled; zero allows only applicable bonuses. Unlimited gaming bypasses restrictions without erasing usage.

Example: daily 60 min, weekend bonus 120 min, weekly 600 min. Weekdays allow 60 min; Saturday and Sunday each allow 180 min, subject to the weekly cap. Add 30 minutes on Saturday grants 210 min that day only, still subject to weekly cap.

Daily gaming time and Weekly gaming time display the same accounted minutes used for policy, independently of enabled restrictions or Unlimited gaming. Daily budget and Weekly budget display remaining percentage. HA 0.5.0 still counts process presence; The foreground accounting follow-up will replace the accounting source.

HA calculates restriction status, and the parent defines actions using ordinary HA automations. Existing Terminate game and Lock PC buttons remain available. The integration no longer selects or executes automated actions itself in the 0.5.0 candidate.

## Foreground accounting

Account only confirmed monitored foreground activity, not merely a running or minimized process. Active game identifies one matched application or idle; Gaming active corroborates the state. Unknown/unavailable is not confirmed idle. Use Recorder and heartbeat coverage; do not guess or retroactively relabel legacy process-presence history. Preserve raw Current game / In game for diagnostics initially. Full native and scoped MQTT support and real Windows acceptance are required.

## Application list

In Settings → Devices & services → SmartHouse Parental Control → select the PC's integration entry → Configure, expose Application list in the Options Flow (not the device page containing budget sliders).

Show the current raw foreground application, including unmonitored applications. A parent focuses the desired application, selects Add application and supplies a readable name. Example: identify Minecraft Java by javaw.exe plus an appropriate identity constraint; Chrome can be monitored as an ordinary application. Show enrolled applications, allow rename/removal, avoid duplicates, and preserve durable per-PC configuration without a service restart. No Steam/Epic catalog is required.

Raw foreground identity and filtered Active game are separate. Active game is the enrolled display name when matched; idle means no monitored foreground application; unknown/unavailable means missing or unreliable detection. Count confirmed non-idle time for overall usage and matching identities for per-application usage. Preserve stable identities across rename; future removal of redundant boolean sensors requires a separate compatibility decision. Do not record browser URLs, window titles, arbitrary command lines or credentials. Enrollment for tracking does not implicitly authorize termination.

## Windows warning popup

A lightweight, child-friendly, Roblox-inspired dark window (not official Roblox branding). Large remaining-time countdown, minutes and seconds in the final minute, and a fixed-width progress track. The colored fill represents remaining time, not consumed time. It is left-anchored and shrinks from right to left: full at the beginning, empty at zero. Fill fraction = remaining / applicable effective allowance, clamped to 0–1. Use the same binding quota for the number and bar. Recompute after allowance changes.

| Remaining time | Color | Warning event |
| --- | --- | --- |
| Above 30 min | Green | At 60 min |
| Above 10 through 30 min | Yellow | Color change only |
| Above 0 through 10 min | Red | At 10 and 1 min |
| 0 min | Red number, empty bar | At zero |

Example for a 120-minute allowance: 120 min = 100% fill; 60 = 50%; 30 = 25%; 10 = 8.33%; 1 = 0.83%; zero = empty. Footer: **Powered by HAL Systems**. Show a short friendly message and a dismiss button. Only one popup instance; dismissal suppresses that warning, not later milestones. If the child returns focus to the game while the window remains open, keep updating its content without repeatedly stealing focus. At zero, the parent's HA automation may terminate the game after validating the restriction, while the popup remains visible at zero independently of the game process.

HA is authoritative for remaining time. Windows displays fresh device-scoped information via a safe interactive-session helper; stale/unknown data cannot become a fabricated countdown or action. No independent Windows enforcement. Future “Just 5 more minutes” request is deferred; no self-granted allowance or automatic approval in the initial version.

## Release discipline

The candidate and backlog design do not replace version-specific installation instructions. Do not present foreground-only accounting, UI enrollment, or popup warnings as already available. Preserve existing device IDs, Recorder history and local configuration during migration. Validate both PCs, scoped/native MQTT and restart/reconnect before production enforcement.
