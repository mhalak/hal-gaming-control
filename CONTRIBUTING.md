# Contributing

Use feature branches and pull requests. Keep device identities, existing topics and configuration compatible. Add regression tests for protocol, accounting, HA runtime and Windows changes. All documentation, code comments and user-facing strings should be English. Follow the release checklist; independently version HA and Windows. Do not add secrets or unsanitized household logs. Confirm changes to the Windows service on a disposable session before release.


## Code signing contributions

The [Code signing policy](CODE_SIGNING_POLICY.md) defines authors, reviewers
and manual release approver responsibilities. External contributions require
maintainer review before merge and **may not** trigger signing or publishing.
Build/installer/signing-policy changes need special scrutiny. A green test
workflow or a GitHub Actions unsigned candidate is not signing approval.
All maintainers and SignPath members must enable MFA.
