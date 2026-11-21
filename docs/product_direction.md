# Product direction — SmartHouse Parental Control

[← Documentation hub](README.md) · [← Project home](../README.md)

*Parent-facing guides:* [Track applications](features/tracked-applications.md) · [Budgets and bonuses](features/gaming-budgets.md) · [Screen idle bonus (planned)](features/screen-idle-bonus.md) · [Budget overview (planned)](features/budget-overview.md)

Powered by HAL Systems.

This document records agreed product behavior, not a claim that each feature is already released. See the [release history](ha_releases.md) and [HA guide](ha_integration.md) for version-specific behavior.

## Delivery roadmap

| Feature | Scope | Status |
| --- | --- | --- |
| Budget model | Daily and weekly time sensors, Weekend bonus, automation-owned enforcement | Partial kernel and action cleanup in 0.5.0 preview; duration sensors/bonus UI/restriction trigger still planned |
| Foreground accounting | Foreground telemetry and foreground-only accounting | Priority follow-up; required before accurate active application accounting |
| Application list | Application list and enrollment from live foreground identity | Backlog improvement |
| Screen idle bonus / AFK grind support | Detect confirmed display-off, let background grinding continue and optionally reward eligible pre-off idle minutes as a daily parent-policy bonus | Planned; [#92](https://github.com/mhalak/smarthouse-parental-control/issues/92) |
| Budget overview | Text-first breakdown of daily, parent, weekend and screen idle bonuses plus measured playtime | Planned; [#93](https://github.com/mhalak/smarthouse-parental-control/issues/93) |
| Countdown popup | Child-facing Windows countdown and warning popup | Backlog improvement; visual behavior agreed |
| Future | Optional request for five more minutes | Deferred until popup UX is validated |

Keep restrictions disabled during development smoke tests; stable releases and trusted binary distribution require validation.

## Target budget model (partially implemented in HA 0.5.0 preview)

Only two independent quotas: **Daily budget** and **Weekly budget**. **Weekend bonus** is an additive allowance, not a third quota or a replacement daily budget. The bonus applies separately on Saturday and Sunday, using HA's local calendar. Unused bonus does not roll over.

Effective finite daily allowance = Daily budget + applicable Weekend bonus + today's one-off bonus (Add 30 minutes). The weekly budget cap is independent and neither bonus increases it. The daily budget remains unlimited when disabled; zero allows only applicable bonuses. Unlimited gaming bypasses restrictions without erasing usage.

Example: daily 60 min, weekend bonus 120 min, weekly 600 min. Weekdays allow 60 min; Saturday and Sunday each allow 180 min, subject to the weekly cap. Add 30 minutes on Saturday grants 210 min that day only, still subject to weekly cap.

Daily gaming time and Weekly gaming time display the same accounted minutes used for policy, independently of enabled restrictions or Unlimited gaming. Daily budget remaining and Weekly budget remaining display unused percentages, while Daily budget and Weekly budget configure allowed minutes. HA 0.5.0 preview still counts process presence; the foreground accounting follow-up will replace the accounting source.

HA calculates restriction status, and the parent defines actions using ordinary HA automations. Existing Terminate game and Lock PC buttons remain available. The integration no longer selects or executes automated actions itself in the 0.5.0 preview; the verified HA restriction trigger remains a follow-up.

## Foreground accounting

Account only confirmed monitored foreground activity, not merely a running or minimized process. Active game identifies one matched application or idle; Gaming active corroborates the state. Unknown/unavailable is not confirmed idle. Use Recorder and heartbeat coverage; do not guess or retroactively relabel legacy process-presence history. Preserve raw Current game / In game for diagnostics initially. Full native and scoped MQTT support and real Windows acceptance are required.

## Application list

In Settings → Devices & services → SmartHouse Parental Control → select the PC's integration entry → Configure, expose Application list in the Options Flow (not the device page containing budget sliders).

Show the current raw foreground application, including unmonitored applications. A parent focuses the desired application, selects Add application and supplies a readable name. Example: identify Minecraft Java by javaw.exe plus an appropriate identity constraint; Chrome can be monitored as an ordinary application. Show enrolled applications, allow rename/removal, avoid duplicates, and preserve durable per-PC HA configuration without any Windows configuration write or service restart. No Steam/Epic catalog is required.

Raw foreground identity and filtered Active game are separate. Active game is the enrolled display name when matched; idle means no monitored foreground application; unknown/unavailable means missing or unreliable detection. Count confirmed non-idle time for overall usage and matching identities for per-application usage. Preserve stable identities across rename; future removal of redundant boolean sensors requires a separate compatibility decision. Do not record browser URLs, window titles, arbitrary command lines or credentials. Enrollment for tracking does not implicitly authorize termination.

## Planned Screen idle bonus and AFK grind support

> **Because the loot won't farm itself.** The child has gone to bed, but their Roblox character has apparently picked up a night shift. We support the grind. We just don't think the family gaming budget needs to work overtime with it.

Parents can choose how generous the household rules should be. **Screen idle bonus is a parenting allowance, not a correction to inaccurate telemetry:** a child who leaves a foreground game running has genuinely consumed gaming time until the display turns off. A stricter parent can leave those minutes charged ("You left it running; your budget noticed"). A more forgiving parent can award eligible pre-off idle minutes back as a **separate, explicitly named Screen idle bonus**. Neither choice rewrites history. Parenting styles vary; the virtual potato farm will survive either way.

**Target behavior (not yet implemented):**

- The Windows companion reports confirmed display state and reliable interactive-session inactivity evidence; Windows display power configuration informs eligibility but is not a reason to invent idle periods. A console session service must not mistake its own session for the child's. Raw keyboard contents, private command lines, window titles and identities are not reported.
- While the monitor is confirmed off, the tracked game may **remain running** for AFK grinding. The HA-owned **Active game** becomes confirmed `idle` and newly elapsed screen-off time is **not** charged to gaming usage. On return and fresh foreground confirmation, normal accounting resumes. No terminate, lock or forced power-setting changes are implied.
- Measured foreground usage **up to the screen-off event** stays in daily, weekly and per-application statistics. With parental permission and reliable last-activity evidence, the system grants up to the eligible measured pre-off idle span as **today's Screen idle bonus**; a manual display-off immediately after input must not earn a fictional full timeout. Bonus events are device-scoped, durable, idempotent and do not survive into the next day's allowance.
- The **effective finite daily allowance** is base daily budget + applicable Weekend bonus + Parent bonus (from Add 30 minutes) + Screen idle bonus. The independent weekly limit is **not** enlarged, and the underlying recorded gaming-time total is **not** decreased. Show all line items transparently in [Budget overview #93](https://github.com/mhalak/smarthouse-parental-control/issues/93).
- Offer a parent-controlled opt-in/policy for automatic Screen idle bonuses, so generous and strict households are both supported. Keep it inactive unless explicitly configured and validated; this roadmap is not authorization to enable enforcement, backfill older history, grant allowances from untrusted or missing telemetry or alter Windows settings.

Illustrative ledger (not live data):

```text
+180 min  Daily budget
 +10 min  Screen idle bonus
 +30 min  Parent bonus
---------------------------
 220 min  Total daily budget
-210 min  Measured gaming time
---------------------------
  10 min  Remaining today
```

The 210 measured minutes remain 210, including in weekly usage. The 10-minute Screen idle bonus is an extra daily allowance, **not** a stealth reduction in measured playtime. A depleted weekly quota still takes precedence when restrictions are enabled.

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
