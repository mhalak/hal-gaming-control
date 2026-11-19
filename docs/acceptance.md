# Windows agent acceptance checklist

- [ ] Fresh install starts automatically under LocalSystem, no visible window, no user account provisioning.
- [ ] HA discovers exactly three sensors and two buttons; device availability follows broker connection and last will.
- [ ] Uptime is machine uptime, not service uptime; it advances across service restart and resets on full Windows reboot (Windows Fast Startup may preserve kernel uptime).
- [ ] Idle reports OFF / idle, launch and exit report promptly (default poll 1 s); minimized game remains active.
- [ ] Minecraft Java, Bedrock and Roblox detected with verified actual process rules; unrelated Java and other processes never terminated.
- [ ] Concurrent games report ON and deterministic sorted names; HA per-game membership can identify both.
- [ ] No automatic termination regardless of elapsed time, HA status, reboot or broker loss.
- [ ] Explicit terminate_game affects all matched games only; test disposable sessions. Reopening a game is permitted unless HA sends a fresh command.
- [ ] Explicit lock_pc locks active console; single active RDP session if no active console; no user logs into a locked or ambiguous session automatically.
- [ ] Lock helper runs without visible window and under the interactive user's token; no password required; no-session case safely ignored.
- [ ] Malformed, unknown, retained, offline and stale queued commands never executed after reconnect; verify with MQTT 5 broker (including a live retained publish).
- [ ] HA birth and MQTT reconnect republish fresh state; uptime updates every 60 s; no duplicate entities.
- [ ] Separate PC IDs and ACLs isolate actions; configuration/logs are protected from non-admin users.
- [ ] Service recovery after termination; no local database or quota state created.
- [ ] Build and install tested on actual Windows PC before deployment to second PC.

HA policy integration is a separate task: daily/week/weekend quotas and per-game history, periodically evaluate and re-evaluate on launch/reconnect; gaps during unavailability are explicitly unknown.
