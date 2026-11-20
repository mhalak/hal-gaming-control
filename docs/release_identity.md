# Internal release identity

`release.json` declares the preview label and independent numeric Windows and HA component versions. The initial declaration records the intended Foreground Preview 1 component versions (0.2.2/0.4.3); it does not assert that those binaries have been installed or that a release exists. Verify existing allocations and bump the appropriate component before distributing different code under an already distributed version. Do not reuse a release tag or overwrite a published package.

## Prepare a version

1. Edit the root release.json once, preserving unrelated component versions.
2. From the repository root run `python tools/release_identity.py sync-ha` to synchronize the tracked HA manifest's version, and review the diff. Run `python tools/release_identity.py check`. The Windows CI test suite checks this consistency on both platforms.
3. Commit the declaration, generated manifest if changed, and release notes; wait for the existing CI gates. Do not prepare a candidate from an unreviewed branch or dirty checkout.
4. On a trusted Windows build host use a fresh checkout of the exact reviewed commit, verify the tree and invoke `windows_agent/build.ps1`. The script emits version.txt and build-info.json into the complete agent onedir package only after successful builds and source identity verification. Explicit Version is optional and is an assertion, not an override.
5. For a manual HA deployment, use `python tools/release_identity.py identity --component home_assistant` from the same clean checkout. Record its JSON in the external deployment record, alongside exact staged component tree identity. HA manifest remains compatible with HACS. Runtime SHA sensors and HA automated staging are follow-ups; HA version currently does not establish exact deployed revision.
6. Record artifact SHA-256, resolved dependencies/toolchain, service path, observed version, exact source SHA, previous known-good version and rollback path. Preserve config/Recorder. Both PCs should receive the same verified package.

The Git SHA is source provenance metadata, not a cryptographic attestation of the binary, reproducibility, authenticity, or live process state. Git status ignores ignored files: use fresh isolated trusted source/build environments without ignored source overrides. Do not ship failed-build output. No public unsigned binaries, automated publishing, remote update activation or Windows-only GitHub Releases in this HACS repository. See [HACS release policy](hacs_release.md) and [Windows deployment](windows_deployment.md).
