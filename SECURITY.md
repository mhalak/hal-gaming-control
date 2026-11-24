# Security

Do not publish credentials, tokens, private broker details, personal data or exploit instructions in public issues. Use GitHub private vulnerability reporting once enabled, or contact the repository owner privately. Describe the affected version and sanitized reproduction steps. The agent runs as LocalSystem, so do not bypass Windows security controls or trust unsigned executables. Do not test unexpected termination or locking on important sessions. This project is not a tamper-proof parental-control boundary.


## Windows signing and household privacy

[Code signing policy](CODE_SIGNING_POLICY.md) · [Privacy policy](PRIVACY.md) ·
[Windows distribution status](docs/windows_distribution.md).

HAL Gaming Control does **not** currently ship SignPath-signed Windows
executables. A future signature must be validated with real Windows
Smart App Control enabled. Do not distribute credentials, private home-network
information or children's app telemetry in bug reports or CI artifacts.
