# MQTT OTA: independent Windows agent release transport

**Status: increment 3 of [issue #166](https://github.com/mhalak/hal-gaming-control/issues/166).** The HA-side MQTT transport can now send scoped packets with ACK/retry, and the opt-in Windows MQTT receiver can stage them. **This is a staging-only developer API, not an HA UpdateEntity Install implementation.** No signed release package source, signature verification at installation, updater handoff, installed-version change, or completed real-PC pilot exists. The existing HTTPS updater and active HA Install behavior are unchanged. **Do not enable this preview on family PCs.**

## Independent versioning and Marketplace

The source lives in the shared `hal-gaming-control` monorepo, but HA releases and Windows binaries have **independent versions and release channels**.

| Component | Example | Distribution |
| --- | --- | --- |
| HA integration | 0.8.0 | HACS / Marketplace from `mhalak/hal-gaming-control` |
| Windows agent | 0.2.10 | Separate, operator-approved Windows binary release repository or distribution server |
| Windows updater | Initially manually bootstrapped | One-time protected Windows service/task provisioning, then explicitly requested upgrades |

Do **not** tag Windows-only binary releases in the HACS integration repository; HACS looks at the repository's release metadata. The distribution repository has not yet been created or provisioned. It requires an approved build, Windows Authenticode signing, pinned Ed25519 release signatures and an authorized publishing flow. No source code change requires a synchronized HA/Windows version bump unless the wire protocol or capability negotiation actually changes.

## Transport v1 — staged bytes only

Both sides now have separate, pure implementations of this byte format:

- HA source: `custom_components/hal_gaming_control/ota_sender.py` — `PackageFrames`; `custom_components/hal_gaming_control/ota_transport.py` — HA `HaOtaTransport` with real MQTT publish/subscribe (not yet invoked by UpdateEntity or exposed as an HA service).
- Windows source: `windows_agent/gaming_control/ota_staging.py` — `StageReceiver` plus `gaming_control/ota_mqtt.py` and the *explicitly gated* MQTT bridge adapter; bytes may be staged, but there is no unpacking or installation.
- Contract tests: `windows_agent/tests/test_ota_contract.py` exercise exact HA-created bytes against the Windows sink; sender and receiver are not imported from one another.

Device-scoped MQTT 5 topics (the three incoming topics and response ACK are **active only after deliberate Windows opt-in**, not on normal installations):

| Topic suffix | Sender | Payload |
| --- | --- | --- |
| `ota/start` | HA | Strict non-retained JSON offer |
| `ota/chunk` | HA | 20-byte header + raw binary chunk |
| `ota/finish` | HA | Strict non-retained JSON finish request |
| `ota/ack` | Windows | JSON status `receiving`, `staged` or `rejected`, exact device ID/transfer ID/next index, QoS 1 non-retained |

An offer carries precisely these keys:

```json
{
  "protocol": 1,
  "device_id": "pc_1",
  "transfer_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "version": "0.2.9",
  "size": 102400,
  "sha256": "a_valid_lowercase_hex_64_character_content_digest",
  "chunk_size": 65536,
  "expires_at": 1700000120
}
```

The placeholder shown for `sha256` describes its expected format, not a valid example digest. Use the SHA-256 digest computed by `PackageFrames`. A binary `ota/chunk` has a fixed **16-byte transfer ID**, **4-byte unsigned big-endian sequential chunk index** and **1 to 65,536 data bytes**. The last chunk must exactly match the remaining length. Maximum package size is **200 MiB**, and the offer must expire within 120 seconds. Finish contains only `protocol`, `device_id` and `transfer_id`.

The Windows sink accepts only the next expected chunk, or an **identical resend of the latest accepted chunk** for QoS 1 duplicate delivery. It rejects duplicate JSON keys, invalid types, wrong PC, filename/path injection, retained/old offers at the future MQTT adapter, oversized/chopped/out-of-order packets and SHA-256 mismatches. Bytes are written incrementally into an exclusively created `ota-<transfer_id>.part` in an **existing, protected, Administrator/SYSTEM-only staging directory** and renamed to `.staged` only after byte count and digest match. No MQTT-provided path or command is ever used. Transfers do not currently survive a process restart; reconnect must start a new transfer ID. Stale partial files are only removed by explicit safe cleanup.

**SHA-256 is not signature verification.** A malicious publisher can choose both bytes and digest. Staged files are *untrusted*, never executable. A separate trusted updater must verify the **pinned Ed25519 signature** over the manifest, the expected version/filename/hash, archive structure and Authenticode requirements before any installation. Never treat a received `.staged` file as an authorized update.

## Next safe increments (not implemented by this PR)

1. **Remaining transport hardening**: the HA ACK-driven sender now exists in the module, but remains unexposed until trusted release provenance is established. It sends stop-and-wait QoS1 non-retained chunks with bounded timeouts/retries, one concurrent upload per destination and executor-based disk reads. No resumability across HA or Windows restarts yet; retry starts a new transfer ID after cleanup. A real broker load test is outstanding. The Windows receiver requires explicit opt-in, exact per-device topics and removes incomplete transfers on reconnect. Broker size limits must allow 65,556-byte binary packets.
2. **HA download and local cache**: from a fixed approved Windows release channel, verify immutable reviewed version / signed manifest, stream only to a currently online agent advertising the matching OTA capability; progress and explicit manual UpdateEntity trigger. Never bundle agent ZIPs with HACS.
3. **Windows updater integration**: accept only a fully authenticated staged package through the existing durable journal, stop/swap/health-check/rollback transaction. Preserve protected `config.yaml`, `device_id` and original service registration. No arbitrary URL/command/package from MQTT.
4. **Bootstrap and hardware acceptance**: provision updater once on each PC by a supervised trusted install, test with Smart App Control enabled, no unsigned executable exemptions. Pilot first on one disposable Windows machine; keep automatic updates and policy enforcement off.

Until those gates are complete, the user-visible HA Windows update entity must remain unavailable rather than exposing a nonfunctional Install button. Do not deploy a staged development artifact.

## Tests

```powershell
cd windows_agent
py -3.12 -m pytest -q tests/test_ota_staging.py tests/test_ota_contract.py
```

And on the HA test runner:

```bash
python -m pytest -q tests/home_assistant/test_ota_sender.py
```

The source-only modules carry no credentials and do not contact GitHub or a Windows PC.

## Explicit Windows staging-only development gate (agent 0.2.10)

This is **not a user deployment procedure**. Development VM only, after the current updater's separate secure bootstrap:

```yaml
update:
  enabled: true
  mqtt_staging_enabled: true
```

The protected local directory `%ProgramData%\\SmartHouseGamingControl\\ota-staging` must exist **before** starting the service and must permit writes only for SYSTEM and Administrators. The service derives its path internally from the already protected configuration directory; MQTT payloads cannot choose any output path. It deliberately fails startup if this explicit setting points to a missing staging directory or is enabled without `update.enabled`.

When enabled, the Windows service subscribes to exactly its own `SmartHouse/Gaming/<device_id>/ota/{start,chunk,finish}` with MQTT 5, QoS 1 and retained deliveries suppressed. It sends non-retained QoS 1 `ota/ack` statuses with `{protocol,device_id,transfer_id,next_index,status}`. All retained OTA commands are ignored. Partial bytes are removed on disconnect or orderly shutdown, and an expired in-progress transfer cannot block a newer transfer. A completed `.staged` artifact remains **quarantined, not authenticated or installed**. No `command/update` is issued from this path.

Provision broker ACLs: only an authorized HA deployment identity may write this PC's incoming OTA topics; the PC may only publish its scoped ACK and normal telemetry. Children and other PCs must never be authorized to publish OTA topics.

This opt-in staging control is not exposed in HA and has not been exercised on actual SYSTEM/Windows hosts. Never interpret its `staged` ACK as approval to run a ZIP or proof of signature verification.

## HA sender (increment 3): stage-only internal API

`custom_components/hal_gaming_control/ota_transport.py` provides `HaOtaTransport(hass).async_stage_package(path, device_id=..., version=...)` for **future trusted internal callers**. The method is not registered as an HA service and is not connected to `WindowsAgentUpdate.async_install`: no user button can currently send an arbitrary local file to a computer. The module does not download packages or grant update rights, and it never calls `command/update`. A successful result is named `staged_unverified`, not `installed`.

The engine attaches an ACK subscription *before* publishing a non-retained offer, then sends each 64 KiB binary block with QoS1 and waits for an ACK with the exact device ID, random 128-bit transfer ID, monotonic next-block index and expected status. It ignores retained/foreign/malformed/duplicate/late ACKs, rejects ahead-of-stream acknowledgements, enforces configurable bounded retries and a single in-progress transfer per device. Only one copy of a block is in flight, avoiding broker floods. Hashing and each block read run through HA's executor, so the event loop does not perform a 200 MiB file hash. A caller may receive progress callbacks (confirmed chunks / total).

The Windows v1 receiver **does not implement idempotent FINISH**: resending FINISH after a lost ACK would incorrectly produce a rejection despite successfully staged bytes. Therefore the HA sender repeats **only START and CHUNK**. It publishes FINISH **exactly once** and reports `OTA finish unconfirmed` on a lost acknowledgement. This is an *unknown outcome*, not proof of failure or a reason to launch a second update. HA unsubscribes on failures/cancellation, preserves the normal gaming stream and never performs installation.

The transfer offer expires within 110 seconds, under the receiver's 120-second upper bound. Large archives that cannot complete in that time fail closed and require a new transfer ID. The sender currently has a strict per-chunk ACK window; do not claim 200 MiB transfer throughput or cross-restart resume until a physical broker soak test. Before enabling user-facing Install, implement a **pinned, authenticated release catalog**, on-disk local approved package cache, signed manifest/Authenticode checks and a trusted Windows updater handoff.

Example test target:

```bash
python -m pytest -q tests/home_assistant/test_ota_transport.py
```

**Not yet implemented:** a production release distributor or a user-facing OTA update action, and no live Windows PC has received a package from this code.
