# HACS / Marketplace publication and version policy

**Current source:** HAL Gaming Control Preview 45 — HA integration **0.16.0**, Windows agent **0.5.2**. Profile Copy (#266) adds a one-submit native configuration dropdown and Configure menu pictograms while preserving destination-local accounting, identity and update authorization boundaries. Windows and Unified MQTT v3 are unchanged. This remains a **development preview**, not a signed Windows distribution or evidence of live deployment. See [HA release history](ha_releases.md) for prior changes.

## #189 — why Marketplace showed a commit after release

An HA integration's `manifest.json` version is independent of the Marketplace download version. The Marketplace shows a seven-character `main` commit when it has no **eligible GitHub Release**. Our first GitHub release `0.12.1` was marked **pre-release**, which the *default Marketplace channel excludes*. Therefore even after a fresh uninstall and reinstall the UI kept showing `5903444`. This was a **release-channel configuration error**, not a user's failed reinstall. Official [Marketplace release rules](https://contributors.home-assistant.io/marketplace/guides/releases/) confirm that only users enabling the Pre-release switch can see a GitHub prerelease. For custom repositories, GitHub metadata refresh can be delayed (documented interval up to 48 hours).

**Correction:** The [guarded HA release workflow](../.github/workflows/publish-ha-preview.yml) now publishes normal GitHub **release metadata** so Marketplace discovers the semantic tag `0.12.1` with no prerelease toggle. The code remains a **0.x development preview**, with warnings in release notes. A regular GitHub release is not a stable 1.0 certification, Windows installer, or production deployment. The workflow can promote an existing tagged prerelease to a regular GitHub release **without changing the immutable tag, packaged HA source or versions**. It refuses to do so if the existing release SHA does not match the tag, if the tag is not an ancestor of main, or if the HA package differs. No Windows binaries or other assets are attached. All eight current-main CI workflows and exact version/notes checks must pass. Five functional/quality workflows may satisfy their main run through verified reuse of the exact PR merge tree; see the CI policy below.

The action runs only on explicit operator invocation: manual GitHub Actions dispatch, or the repository owner's exact comment `/publish-ha-release 0.12.1` on issue #189. For subsequent versions, bump only the HA component in `release.json`, sync `manifest.json`, update `docs/ha_releases.md` and invoke the workflow after 8/8 green CI. Never create Windows-only GitHub Releases in this HACS repository. Never retag old source; only the prerelease **classification** can be corrected for this exact identical HA version.

**Verification after GitHub publication:** Check that `GET /repos/mhalak/hal-gaming-control/releases/latest` returns tag `0.12.1`, rather than 404. Then, when Marketplace refreshes custom-repository metadata, the *available version* should read `0.12.1`, without turning on Pre-release. Do not treat a GitHub API success as evidence of a UI change on the user's HA; the user may need to refresh the repository, and we must explicitly verify what the UI says. For existing commit-installed clients, a known [commit-to-release transition issue](https://github.com/hacs/integration/issues/5504) may require a one-time **Redownload → select 0.12.1** when authorized. The user has already uninstalled/reinstalled; never repeatedly recommend reinstall as a fix.

The project continues to use **local agents** for fast development deployment. The GitHub release is strictly metadata/distribution source for Marketplace and must not update, restart or reconfigure the TrueNAS HA instance, Windows PCs, MQTT broker, or any parental policy. Separate production signing, backup, rollback and first-PC acceptance remain mandatory for #56.

## Marketplace domain identity

HA 0.6.1's former `parental_control` domain collided with [cesbron-dev/ha-parental-control](https://github.com/cesbron-dev/ha-parental-control), causing the wrong Marketplace icon and an installation collision. Source preview HA **0.7.0** adopts the distinct domain `hal_gaming_control` ([issue #146](https://github.com/mhalak/hal-gaming-control/issues/146)). The existing HAL artwork is packaged at `custom_components/hal_gaming_control/brand/icon.png` and `icon@2x.png`.

**Do not claim the public Marketplace listing or pre-install icon is already fixed.** Catalog/release icon indexing and a fresh Marketplace install still need external checks on HA 2026.11. If the Marketplace Download dialog suggests any directory other than `hal_gaming_control`, **cancel**. Stable catalog submission remains gated on official validation, physical smoke testing and release requirements.

## Source-only development preview

Core Terminate game and Lock PC actions worked in live smoke testing. Source publication does not certify stable release acceptance. Keep personal data, credentials, private diagnostics and development history out of the public repository. Do not distribute unsigned executables as trusted releases. This preview has no approved Windows binary build, signed Windows artifact upload or Windows distribution release workflow. An independently gated **HA-only versioned GitHub release** workflow exists for Marketplace; it never packages or installs Windows binaries. Windows CI runs source tests and compilation checks only; local packaging remains available for development. The [disabled design reference](examples/windows-release.yml.disabled) is retained for development only; it signs the update manifest, not the executable, and must never be enabled in this repository.

## Source-preview gates

- The owner confirmed the three branding assets' AI-generated origin and authorized redistribution; see [asset provenance](../ASSETS.md). Verify that the published files match that record.
- All active GitHub Action references are pinned to reviewed upstream commit SHAs; all active workflows specify read-only contents permissions and checkout does not persist credentials. Both upstream actions still invoke mutable container tags; SHA pinning does not make the full toolchain immutable. Review the resolved images or use digest-pinned validation before claiming reproducible validation. HACS PR commenting is disabled and workflow token permissions remain read-only.
- All eight workflow results must be green for the exact current main SHA before any HA GitHub release. A main run may reuse functional/quality evidence only under the strict policy below; unrelated past green runs never certify future commits. No stable 1.0 or official catalog listing is authorized by source-only publication.

## Main CI: verified PR tree reuse (#272)

All eight PR workflows execute fully for each PR revision, recording the actual synthetic merge SHA via GitHub's run name. On a main push, the five functional/quality workflows (HA, Windows, Direct MQTT, Recorder and Python quality) first check authoritative GitHub API evidence. They may skip repeating the heavy jobs only for one same-repository PR actually merged at that exact main SHA, with all eight latest PR runs green before merge, one identical recorded synthetic merge SHA, matching base/head parents and an identical full Git tree. The lightweight main verification job logs the PR, tree, merge SHA and run IDs. PR and manual runs never reuse; direct pushes, multi-commit pushes, fork PRs, stale or missing runs, unavailable Git objects/API errors and differences fall back to full tests.

CodeQL, Security CI and HACS validation always execute on main because security reporting, Git history and external validation context differ. Scheduled security checks remain intact. Release publishing still requires eight successful main-push workflow results and retains all version, immutable-tag and operator guards. No artifact trust or Windows deployment requirements change. When evidence is reused, full test/coverage artifacts remain attached to the originating PR runs, not duplicated on main.

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
