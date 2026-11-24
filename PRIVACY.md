# Privacy policy — HAL Gaming Control

**Last updated: 24 November 2026 · Windows/HA development preview**

HAL Gaming Control is a self-hosted parental gaming-time monitoring and
control tool. Families operate their own **Home Assistant** instance and an
MQTT broker. The Windows agent connects to the broker that the administrator
specifies in its private configuration. No HAL Systems account or proprietary
gaming-control cloud is required.

This policy describes the project's intended and current source behavior,
not every possible way a third-party broker, HA installation or network might
be configured. It is **not** a promise that a user-specified broker is local or
that traffic is encrypted when the administrator chooses plain MQTT.

## Data processed and purpose

The Windows service and Home Assistant exchange only data needed for
configured game/app tracking and parental actions:

- **PC identity:** Windows computer name as MQTT `device_id`, software
  version and build diagnostic, online/offline state and uptime.
- **Gaming observations:** currently foreground executable/process identity
  (and limited identifying process context when needed to validate
  applications), active/idle state, and timestamps needed for verified screen
  time. Some diagnostic and enrollment messages include process identity.
- **Display state:** console display activity / screen-off observations,
  timing and freshness for accurate gaming accounting.
- **Parent controls:** bounded game termination offers and results, PC-lock
  commands, HA-managed budgets, schedule restrictions and bonus history.
- **Popup interaction:** temporary text, countdown and percentage selected by
  the parent, plus response button IDs / close events; these are visible to the
  person signed in at the PC.
- **Technical diagnostics:** connection errors and limited process/game
  identifiers in protected local service logs. These can be sensitive and
  should not be shared publicly.

The current protocol is the device-scoped **Unified MQTT v3** monitoring
snapshot, plus separate command/discovery/popup/update channels. We do not
record screenshots, webcam video, keystrokes, browser history or the content
of chats. The agent detects foreground applications, which can nonetheless
reveal a child's interests or activity; treat this information as sensitive.

## Where data goes

- **Configured MQTT broker:** the Windows agent connects to the host specified
  by the parent/administrator. It sends device-scoped telemetry, discovery,
  availability, diagnostics and response events, and receives authorized
  commands. MQTT accounts and broker ACLs are controlled by the operator.
- **Home Assistant:** receives observations and keeps budget, bonus and
  retained Recorder history according to the owner's configuration,
  integrations and retention policy. HA automations can further forward
  events if the operator configures them.
- **This project:** no built-in analytics, advertising network, mandatory
  external telemetry service or HAL-operated cloud endpoint for gaming data.
- **Optional updater:** disabled by default. Only if an administrator
  separately configures and enables trusted updates may the updater contact
  an approved HTTPS release mirror. The mirror's operator, not this project,
  controls its server logs and data handling. A GitHub page viewed by the
  user and downloads requested by the user are also separate network
  interactions.
- **SignPath Foundation:** if public code signing is approved, SignPath
  receives the software *build artifact* and its build provenance. This is a
  release-time developer operation; **child/household telemetry is not sent
  to SignPath** by this application.

Default plain MQTT (port 1883) is not transport-encrypted; configuring TLS and
per-PC topic ACLs is the administrator's responsibility. A broker may be remote
if the administrator deliberately sets a remote address. The app does not
silently change the destination.

## Storage, retention and access

Windows stores protected configuration and local service logs under its
application-specific `ProgramData` directory; application binaries live in
`Program Files`. The broker may retain discovery/availability metadata;
short-lived telemetry and popup events are intentionally non-retained.
Home Assistant stores gaming usage, parent budget options and history as
controlled by the operator and HA Recorder settings. Retention durations
therefore depend on deployment and are **not centrally configured or read by
HAL Systems**.

MQTT credentials are held in protected configuration; the project does not
ask families to upload broker credentials to the public repository or SignPath.
Windows services run under LocalSystem; restrict administrator access and use
distinct, device-scoped MQTT identities. The connected user can see the popup.

## Control, deletion and children

The installing adult decides which applications to track and configures
budgets, alerts and device controls in Home Assistant. Children should be
informed appropriately that their gaming activity is monitored. The app
does not require identifying a child by legal name.

To stop collection, disable the relevant HA enrollment/automation and stop
or uninstall the Windows service. The documented `uninstall.ps1` intentionally
**retains ProgramData configuration, logs and recovery evidence** for safe
rollback; an administrator must review and delete project-owned retained files
separately when no longer required. Home Assistant Recorder history and
broker retained entries must likewise be reviewed/deleted under their
respective tools and retention policies. Do not clear unrelated MQTT topics
or HA data to remove one PC.

## Third-party components

The application relies on Windows, Python and its packaged dependencies,
Home Assistant and the MQTT broker chosen by the administrator. Such software
can have its own privacy policies and optional online features. The Windows
agent does not enable third-party analytics on behalf of HAL Systems.
See [requirements](windows_agent/requirements.txt) and
[Home Assistant](https://www.home-assistant.io/privacy/).

## Questions and security reports

Use [repository issues](https://github.com/mhalak/hal-gaming-control/issues)
for non-sensitive questions. For vulnerabilities, use
[SECURITY.md](SECURITY.md); never include children's names, broker addresses,
credentials or raw diagnostic files in public reports.

This project is provided under the MIT license as development preview
software. SignPath code signing, if approved, verifies build origin and does
not change this data policy.
