# Known limitations and release blockers

SmartHouse Parental Control — Powered by HAL Systems

Development preview. This is a record of observed limitations, not instructions to weaken Windows security. See [product direction](product_direction.md) for the agreed roadmap.

## Verified core functionality

Maintainer-observed live smoke test: Terminate game — PASS; Lock PC — PASS. Both explicit actions work on request. Per-PC coverage and exact tested versions were not specified by the owner; this does not certify all target devices, automatic policy enforcement or foreground accounting.

A public source-only development preview is distinct from a stable 1.0.0 release and trusted binary distribution. Unresolved signing, CI and functional acceptance remain mandatory gates for stable release.

## Windows Smart App Control and signing — release blocker

During manual deployment of Windows agent 0.2.1, Windows 11 Smart App Control (SAC) blocked the unsigned service executable under the VerifiedAndReputableDesktop Code Integrity policy. The observed service-start failure was error 4551 (SCM event 7000). Elevation did not resolve the block. One test PC with SAC already Off ran 0.2.1; the other initially required rollback. Both local builds were unsigned.

In controlled development testing, the blocked unsigned build subsequently ran on a system where SAC was Off, with Defender protections still enabled. This does not establish compatibility with SAC enforced. Do not disable Windows security to install this software. No signed build has yet passed SAC-enforced acceptance.

The permanent solution is trusted Windows Authenticode signing of applicable binaries, with verification of the final package, trust chain and timestamp. Ed25519 release-manifest signatures authenticate the update package but do not establish Windows executable trust. Signing pipeline development remains incomplete; no trusted signed distribution is advertised. No certificate purchase or provider enrollment is assumed. Do not disable SAC, Defender or other security controls on production installations to run an unsigned or blocked executable. Stop and report deployment failures; preserve the last working installation.

Public release gate: produce reviewed, signed, versioned artifacts, verify those artifacts on a real SAC-enforced Windows system, and validate the installation and update/rollback path.

## Other current limitations

| Area | Known limitation | Follow-up / boundary |
| --- | --- | --- |
| HA accounting | Main 0.4.2 and HA 0.5.0 candidate still count configured running processes, including minimized/background games. Windows foreground telemetry exists but scoped HA entities and foreground-only accounting are missing. | Verify actual foreground MQTT on both PCs before enabling restrictions. |
| HA 0.5.0 | Daily/weekly time sensors, additive Weekend bonus and automation-only enforcement are an implementation candidate, not a confirmed validated deployment. | Not included in this source snapshot. Preserve config and history; incompatible legacy weekend overrides require explicit migration. |
| Foreground helper | Agent 0.2.0 had a named-pipe access failure; 0.2.1 includes a permissions fix. Full real interactive-session acceptance is not established by idle telemetry or an isolated IPC test. | #38; verify Alt+Tab, minimized games, lock/unlock and stale/unknown states. |
| Configured applications | Currently matches explicit executable rules in protected local YAML; unconfigured applications are not tracked and config changes require service restart. | Parent enrollment in HA Options Flow is planned. |
| Warnings | No Windows countdown overlay or extra-time request UI in current agent. | Popup in backlog, request feature deferred. |
| Remote updater | Disabled until trusted signing and distribution prerequisites, approved catalog/key configuration and update/rollback acceptance are satisfied. | Trusted manual deployment remains the development path. |
| Recorder and connectivity | Unobserved intervals are excluded under heartbeat coverage; missing history cannot be reconstructed reliably. HA/MQTT outages prevent central enforcement. | See [Recorder coverage](recorder_coverage.md); do not label unknown as confirmed idle or retrospectively reinterpret process history as foreground time. |
| Enforcement | Not tamper-proof: a local administrator can stop the service; Windows lock is not permanent lockout; termination can lose unsaved progress. | Keep restrictions disabled during smoke tests; enforce only verified policies using authorized commands. |
| Platforms | Windows 10/11 x64 agent only. Other platforms and browser-tab-level tracking are not supported. | Browser app enrollment, if implemented, tracks the application rather than a specific tab. |
| CI and publication | Hosted GitHub Actions jobs have failed to start due to a billing/spending-limit issue on verified prior runs; some newer failed-job logs are unavailable. Local checks are partial evidence, not a green hosted CI or public release. | Resolve CI and run formal acceptance before 1.0.0. HACS catalog inclusion is pending. |

## Development versus production

Development exceptions must not become product instructions or be treated as release acceptance. Document exact versions and observed outcomes, keep configuration and logs private, and never publish personal identifiers, local paths or raw personal telemetry. See [Windows deployment](windows_deployment.md), [foreground migration](foreground_accounting_migration.md), and [HACS release checklist](hacs_release.md).
