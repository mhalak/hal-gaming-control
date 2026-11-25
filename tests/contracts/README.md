# Shared MQTT protocol contract fixtures

This directory is the **shared compatibility contract** between the actual Windows
MQTT publisher and the Home Assistant consumer. All fixture payloads are valid,
non-retained JSON examples with intentionally *fixed* sample times and opaque IDs.

| Versioned message | MQTT topic | Windows producer coverage | HA consumer coverage |
| --- | --- | --- | --- |
| `v3/telemetry-foreground.json` | `SmartHouse/Gaming/{device_id}/state/telemetry` | `windows_agent/tests/test_unified_telemetry.py` publishes a real Bridge sample and verifies the complete JSON structure and values | `tests/home_assistant/test_options_flow_tracked_apps.py` decodes it and verifies the actual Tracked apps Options Flow |
| `v1/foreground-candidate.json` | `SmartHouse/Gaming/{device_id}/state/foreground_candidate` | `windows_agent/tests/test_unified_telemetry.py` checks the real candidate publication | `tests/home_assistant/test_options_flow_tracked_apps.py` verifies the candidate during Add/Save and rejects invalid scope/retention |

| `v2/popup-upsert.json`, `v2/popup-refresh.json` | `SmartHouse/Gaming/{device_id}/ui/popup` | HA producer: `tests/home_assistant/test_native_actions.py` verifies actual service publication | Windows consumer: `windows_agent/tests/test_popup_protocol.py` drives real Bridge/decoder and model |

Popup v2 is HA → Windows (the producer/consumer roles are reversed from telemetry). The separate discovery capability `popup_ui_protocols: [1, 2]` preserves v1 clients; Unified MQTT v3 monitoring is unchanged.

## Rules

1. **Do not edit an existing versioned fixture to make new code green.** A
   wire-breaking change requires a *new* protocol version and a corresponding
   immutable fixture, while maintaining old-version fixtures for any still
   supported senders/receivers. An intentional clean cut explicitly retires
   the old-version consumer and migration path, with tests proving that decision.
2. The fixture is **not** a Python helper returning the current implementation
   schema. Windows tests must exercise the production serializer and MQTT
   publisher and compare the resulting wire payload to the independent fixture.
   HA tests must pass the exact shared fixture through production parsers and
   the end-user Options Flow without mocking the parser or supplying v2 state.
3. Dynamic fields (epoch, transport time, tiny sample age jitter) may be
   normalized *only after* independent checks of field type, constraints and
   freshness. Every static field and the full nested shape must match.
4. Check producer and consumer test names in this matrix when changing a
   protocol. A new monitoring/discovery/action message adds a versioned
   example and paired producer/consumer tests, even if only one component
   changed in the PR. Run Windows **and** HA CI for protocol changes.
5. Keep invalid-message tests for wrong device, retained, stale, malformed and
   unauthorized application enrollment in addition to happy-path contracts.

A shared fixture helps detect **format drift**; it cannot prove local broker
credentials, QoS delivery in a real network, running Windows services or
physical HA deployments. Those remain separate acceptance checks.
