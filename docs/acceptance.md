# Windows agent acceptance checklist

- [ ] Fresh install starts automatically under LocalSystem, no visible window, no user account provisioning.
- [ ] HA 0.7.2 + Windows 0.2.9: with an empty local catalog, target offers are nonretained/expiring, device-scoped and contain no PID/path/argv/user; `Terminate active game` is available only for the same HA-enrolled, live, verified foreground application in native or scoped MQTT.
- [ ] A legitimate single press consumes a capability once; retries, duplicate payloads, wrong device/epoch, retained/stale/malformed MQTT and broker reconnect never reuse the capability.
- [ ] Windows receives no arbitrary target PID/name/path. Before one-process termination it requires a new post-offer user-session foreground sample matching PID/creation time/session/safe Java signature, verifies process identity and OS path protections; a switched/ambiguous session or window fails closed.
- [ ] Two distinct processes with the same executable name are never treated as interchangeable. Untracked/system/background apps cannot be terminated via the HA manual action; direct scoped and native HA buttons have no duplicate enabled controls.
- [ ] An explicit target failure leaves all games untouched; only the exact verified one stops on a successful authorized physical pilot. Do not send this command to a valuable unsaved game.
- [ ] PCs with legacy games keep their original terminate function unchanged; new target protocol does not activate on those PCs. No automatic policy enforcement or updates are enabled.
- [ ] New PC with only MQTT connection settings starts with no local `games`, sends uptime and raw v2 foreground identity, provides Lock PC and never subscribes to the legacy terminate command.
- [ ] Rule-free PC publishes only exact agent-owned native terminate button tombstone; scoped/direct HA stale terminate action is unavailable when the agent revokes it, even if HA entry still lists the old action.
- [ ] Existing PC with legacy games keeps the same manual Terminate game behavior and verified process constraints after upgrade; removing games is explicitly optional.
- [ ] Malformed or cross-device discovery cannot reactivate a disabled direct terminate button; no other PC command topics or entity registry entries are removed.
- [ ] Without a manual device section, service reports the actual Windows computer name; it generates a per-install ID in protected ProgramData/device_id and reuses it after restart and Windows computer rename.
- [ ] Legacy config device.id is preserved verbatim and saved into the ID file; removing the legacy device section later does not create another HA device or reset budgets/history.
- [ ] Two PCs on the same broker have distinct identities and device-scoped topics. A mismatch/corrupted persisted identity prevents startup instead of silently re-enrolling; never share identity files.
- [ ] In HA, override the default discovered PC name with a user-defined friendly name; subsequent service restart/hostname changes must not replace a name_by_user override or create duplicate entities.
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
