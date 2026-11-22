# HACS / Marketplace publication and version policy

**Current source candidate:** HAL Gaming Control Preview 22, HA integration **0.12.1**, Windows agent **0.4.0**. The canonical HA domain is `hal_gaming_control` under `custom_components/hal_gaming_control`. This is a development **prerelease**, not a production deployment or a signed Windows distribution. See [#56 deployment HOLD](https://github.com/mhalak/hal-gaming-control/issues/56).

## Fix for commit SHA displayed as version (#189)

Marketplace/HACS displays a seven-character `main` SHA when this repository has **no published GitHub Releases**. The HA manifest's `version` is a separate runtime identifier; adding `version` to `hacs.json` is not the fix. Publish an actual GitHub **prerelease** tagged with the exact HA manifest version, currently `0.12.1`. GitHub tag, release, root `release.json` and HA manifest must agree. No Windows-only releases, Windows executable assets or stable 1.0 labels.

The reviewed [`Publish HA preview release`](../.github/workflows/publish-ha-preview.yml) workflow is **operator initiated only**. Run it manually from GitHub Actions on `main`. For the first issue #189 publication, the repository owner may instead comment **`/publish-ha-preview 0.12.1`** on #189 to trigger that one scoped run. The workflow checks the exact current `main` SHA, source/manifest/release notes, all eight completed successful `main` push workflows on that SHA, and whether the release/tag already exists. It refuses to retag or reuse an unchanged version with modified HA package files. It publishes a GitHub HA-only *prerelease* with no assets. **It does not install anything**.

On a **disposable test HA only**, open Marketplace/HACS, enable prereleases for the custom repository, refresh its metadata and confirm it offers `0.12.1` instead of only a SHA. A known HACS [commit-to-first-release update issue](https://github.com/hacs/integration/issues/5504) can leave existing commit-installed versions stuck as `up-to-date`. When authorized, use the integration's **three-dot menu → Redownload → select 0.12.1**, and restart HA if needed. This is a one-time client migration, **not** automatic; no live HA redownload while #56 HOLD is active. Keep the local-agent deployment method for rapid source iterations.

For later HA changes, increment only the HA version in `release.json`, sync `custom_components/hal_gaming_control/manifest.json` using `python tools/release_identity.py sync-ha`, update `docs/ha_releases.md`, pass CI and explicitly run the workflow again. Windows-only source changes must not create a new HACS release. A published tag/version is immutable. Future full HA/Windows integrated deployment is separately authorized and backed up.

## Marketplace domain identity

HA 0.6.1's former `parental_control` domain collided with [cesbron-dev/ha-parental-control](https://github.com/cesbron-dev/ha-parental-control), causing the wrong Marketplace icon and an installation collision. Source preview HA **0.7.0** adopts the distinct domain `hal_gaming_control` ([issue #146](https://github.com/mhalak/hal-gaming-control/issues/146)). The existing HAL artwork is packaged at `custom_components/hal_gaming_control/brand/icon.png` and `icon@2x.png`.

**Do not claim the public Marketplace listing or pre-install icon is already fixed.** Catalog/release icon indexing and a fresh Marketplace install still need external checks on HA 2026.11. If the Marketplace Download dialog suggests any directory other than `hal_gaming_control`, **cancel**. Stable catalog submission remains gated on official validation, physical smoke testing and release requirements.

## Source-only development preview

Core Terminate game and Lock PC actions worked in live smoke testing. Source publication does not certify stable release acceptance. Keep personal data, credentials, private diagnostics and development history out of the public repository. Do not distribute unsigned executables as trusted releases. This preview has no approved Windows binary build, signed Windows artifact upload or Windows distribution release workflow. An independently gated **HA-only source prerelease** workflow exists for HACS; it never packages or installs Windows binaries. Windows CI runs source tests and compilation checks only; local packaging remains available for development. The [disabled design reference](examples/windows-release.yml.disabled) is retained for development only; it signs the update manifest, not the executable, and must never be enabled in this repository.

## Source-preview gates

- The owner confirmed the three branding assets' AI-generated origin and authorized redistribution; see [asset provenance](../ASSETS.md). Verify that the published files match that record.
- All active GitHub Action references are pinned to reviewed upstream commit SHAs; all active workflows specify read-only contents permissions and checkout does not persist credentials. Both upstream actions still invoke mutable container tags; SHA pinning does not make the full toolchain immutable. Review the resolved images or use digest-pinned validation before claiming reproducible validation. HACS PR commenting is disabled and workflow token permissions remain read-only.
- Hosted CI and HACS validation must pass on the exact current main SHA before any HA prerelease; a past green run does not certify future commits. No stable 1.0 or official catalog listing is authorized by source-only publication.

## Before stable release

- Confirm license and assets are suitable for redistribution.
- Confirm canonical repository links, GitHub metadata and private vulnerability reporting.
- Validate workflows and package contents; never expose secrets to untrusted contributions.
- Resolve the known limitations and record formal acceptance evidence.

## HACS checks
- Preserve the existing local `custom_components/hal_gaming_control/brand/icon.png` and `icon@2x.png`; once the unique domain is selected, verify Marketplace **pre-install** imagery against current catalog/release indexing rules and **installed** icons against the local Brands API. Do not submit custom integration images to the legacy `home-assistant/brands` route; follow the HA 2026.3+ local brand conventions.
- One integration under custom_components/hal_gaming_control; runtime files and brand assets within that directory.
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
