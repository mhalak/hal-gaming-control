> **Current acceptance baseline (HA 0.13.0+, Windows 0.4.0+):** only Unified MQTT v3 monitoring is supported. There is no protocol opt-in or fallback. All PC samples must be scoped to the current Windows hostname.

# Windows agent acceptance checklist

- [ ] Every HA gaming PC must advertise `unified_telemetry_protocol: 3`; the HA Configure menu has no telemetry protocol toggle.
- [ ] A stale HA setting `unified_telemetry_enabled: false` is scrubbed without changing tracked applications, policies, bonuses or Recorder history.
- [ ] All six parent-facing sensors recover from valid hostname-scoped v3 packets; v2 monitoring and old scalar Uptime do not update any HA sensor.

- [ ] Fresh install starts automatically under LocalSystem, no visible window, no user account provisioning.
- [ ] HA 0.7.2 + Windows 0.2.9: with an empty local catalog, target offers are nonretained/expiring, device-scoped and contain no PID/path/argv/user; `Terminate active game` is available only for the same HA-enrolled, live, verified foreground application in native or scoped MQTT.
- [ ] A legitimate single press consumes a capability once; retries, duplicate payloads, wrong device/epoch, retained/stale/malformed MQTT and broker reconnect never reuse the capability.
- [ ] Windows receives no arbitrary target PID/name/path. Before one-process termination it requires a new post-offer user-session foreground sample matching PID/creation time/session/safe Java signature, verifies process identity and OS path protections; a switched/ambiguous session or window fails closed.
- [ ] Two distinct processes with the same executable name are never treated as interchangeable. Untracked/system/background apps cannot be terminated via the HA manual action; direct scoped and native HA buttons have no duplicate enabled controls.
- [ ] An explicit target failure leaves all games untouched; only the exact verified one stops on a successful authorized physical pilot. Do not send this command to a valuable unsaved game.
- [ ] PCs with legacy games keep their original terminate function unchanged; new target protocol does not activate on those PCs. No automatic policy enforcement or updates are enabled.
- [ ] New PC with only MQTT connection settings starts with no local `games`, sends uptime and fresh unified v3 foreground telemetry, provides Lock PC and never subscribes to the legacy terminate command.
- [ ] Rule-free PC publishes only exact agent-owned native terminate button tombstone; scoped/direct HA stale terminate action is unavailable when the agent revokes it, even if HA entry still lists the old action.
- [ ] Existing PC with legacy games keeps the same manual Terminate game behavior and verified process constraints after upgrade; removing games is explicitly optional.
- [ ] Malformed or cross-device discovery cannot reactivate a disabled direct terminate button; no other PC command topics or entity registry entries are removed.
- [ ] Service reports the actual Windows computer name as MQTT ID and discovery name. It survives agent restart but a Windows hostname rename deliberately changes the device namespace and requires HA re-enrollment.
- [ ] Windows agent 0.4.0+ rejects the former `device:` YAML block; no persisted ID overrides the Windows hostname.
- [ ] Two PCs on the same broker have distinct OS hostnames and device-scoped topics. Reject invalid/duplicate hostnames rather than silently inventing identities.
- [ ] In HA, override the default discovered PC name with a user-defined friendly name; subsequent service restart/hostname changes must not replace a name_by_user override or create duplicate entities.
- [ ] HA sensors derive live data only from non-retained Unified v3; native MQTT Uptime reads its existing entity from the v3 JSON, not a scalar state topic.
- [ ] Uptime is machine uptime, not service uptime; it advances across service restart and resets on full Windows reboot (Windows Fast Startup may preserve kernel uptime).
- [ ] Verified v3 `foreground.state` reports `foreground`, `idle` or `unknown` with fresh observation age; HA does not infer idle from missing data.
- [ ] Minecraft Java, Bedrock and Roblox detected with verified actual process rules; unrelated Java and other processes never terminated.
- [ ] A single validated foreground process is authoritative in each v3 snapshot; HA owns tracked-app naming and confirmed time.
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
