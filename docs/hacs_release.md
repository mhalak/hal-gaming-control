# HACS publication checklist

Public product name: SmartHouse Parental Control. Proposed repository slug: smarthouse-parental-control. Keep the existing integration domain/directory `smarthouse_gaming`, MQTT root `SmartHouse/Gaming`, entity unique IDs and Windows service name. A repository/display-name change must not become an entity migration.

## Source-only development preview

Core Terminate game and Lock PC actions worked in live smoke testing. Source publication does not certify stable release acceptance. Keep personal data, credentials, private diagnostics and development history out of the public repository. Do not distribute unsigned executables as trusted releases. This preview has no active Windows binary build, artifact upload or release workflow. Windows CI runs source tests and compilation checks only; local packaging remains available for development. The [disabled design reference](examples/windows-release.yml.disabled) is retained for development only; it signs the update manifest, not the executable, and must never be enabled in this repository.

## Source-preview gates

- The owner confirmed the three branding assets' AI-generated origin and authorized redistribution; see [asset provenance](../ASSETS.md). Verify that the published files match that record.
- All active GitHub Action references are pinned to reviewed upstream commit SHAs; all active workflows specify read-only contents permissions and checkout does not persist credentials. Both upstream actions still invoke mutable container tags; SHA pinning does not make the full toolchain immutable. Review the resolved images or use digest-pinned validation before claiming reproducible validation. HACS PR commenting is disabled and workflow token permissions remain read-only.
- Hosted CI and official validation have not yet passed. Record these as outstanding, not successful; no stable release or listing is authorized by source publication.

## Before stable release

- Confirm license and assets are suitable for redistribution.
- Confirm canonical repository links, GitHub metadata and private vulnerability reporting.
- Validate workflows and package contents; never expose secrets to untrusted contributions.
- Resolve the known limitations and record formal acceptance evidence.

## HACS checks
- Prepare the icon assets for a future home-assistant/brands PR under custom_integrations/smarthouse_gaming/. A local brand/icon.png alone does not satisfy the documented default-catalog Brands check. Verify the latest upstream requirements before submission. Do not submit either upstream PR yet.
- One integration under custom_components/smarthouse_gaming; runtime files and brand assets within that directory.
- Root hacs.json and README, identifiable OSI license, useful GitHub metadata.
- Run local packaging validation on every PR. Run official HACS validation and Hassfest without ignores once public; fix failures before publication.
- Minimum HA version is conservatively set to 2026.10.2, the current tested deployment baseline. Validate more versions before lowering it.
- Confirm install, update, uninstall and rollback on a disposable HACS-enabled HA instance; verify preserved config entries/entities and MQTT behavior.
- Finish the foreground accounting and automation-only migration, actual Windows acceptance, and verified Windows distribution before claiming those features.
- Resolve Windows signing: trusted Authenticode signing and real SAC-enforced Windows installation/update acceptance; unsigned local development exceptions and Ed25519 manifest authentication are not equivalent. Resolve hosted CI blockers and review [known limitations](known_limitations.md) before 1.0.0.
- For this project's release policy, publish an HA GitHub Release with semantic tag matching the manifest after checks pass. Do not publish Windows-only GitHub Releases in this same HACS repository: HACS selects releases at repository level. Use a separate approved Windows distribution repository or publish Windows artifacts through a separate channel; don't mix Windows-only release tags into HACS stable versions. Do not publish unsigned executables as trusted releases.
- Use render_readme: true so HACS displays the documentation. Test adding as a custom repository. Once public, release exists and checks pass without ignores, owner/major contributor can submit to hacs/default alphabetically. Review/acceptance is not automatic.

Official documentation:
- https://www.hacs.dev/docs/publish/integration/
- https://www.hacs.dev/docs/publish/start/
- https://www.hacs.dev/docs/publish/include/
- https://www.hacs.dev/docs/publish/action/
