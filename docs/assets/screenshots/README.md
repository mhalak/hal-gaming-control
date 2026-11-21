# Screenshot capture checklist

[← Documentation](../../README.md)

Documentation screenshots must be **real, version-verified and privacy-safe**. Do not use a generated mock-up to imply a future feature is already shipped.

## Existing preview flows — capture from the validated HA/Windows test setup

| File to add here | Page | What to show | Status |
| --- | --- | --- | --- |
| `tracked-apps-detected.png` | [Track an application](../../features/tracked-applications.md) | Currently detected safe executable identity, HA display name, no private values | Needs real capture |
| `tracked-apps-list.png` | [Track an application](../../features/tracked-applications.md) | Application List with at least two fictional labels, Add/Edit/Delete | Needs real capture |
| `tracked-apps-save-mobile.png` | [Track an application](../../features/tracked-applications.md) | Android nested Add then outer Save changes, labels visible | Needs real capture |
| `gaming-budgets-device.png` | [Gaming budgets](../../features/gaming-budgets.md) | Daily/weekly budget and current gaming-time entities on correct PC | Needs real capture |
| `parent-bonus-30.png` | [Gaming budgets](../../features/gaming-budgets.md) | Add 30 minutes and changed allowance, when validated | Needs real capture |
| `manual-actions.png` | [Manual actions](../../features/parent-actions.md) | Lock PC and Terminate game with safe sample PC label | Needs real capture |

## Future features — capture only after real deployment

| File to add here | Page | Status |
| --- | --- | --- |
| `screen-idle-setting.png` | [Screen idle bonus](../../features/screen-idle-bonus.md) | Not implemented — do not capture a fake control |
| `screen-idle-award.png` | [Screen idle bonus](../../features/screen-idle-bonus.md) | Not implemented — capture a validated bonus event later |
| `budget-overview.png` | [Budget overview](../../features/budget-overview.md) | Not implemented — capture the native HA Markdown card once deployed |

## Before committing images

1. Record the **exact HA integration and Windows agent versions**, and identify whether the screenshot comes from Android, desktop or mobile browser.
2. Use a sanitized test PC and **fictional display labels** (for example `Gaming PC`, `Roblox`, `Minecraft`). Never publish real children's names, family photos, account identifiers, local IPs, hostnames, MQTT credentials, tokens, auth URLs, private paths or debug messages.
3. Crop to the relevant card/dialog while retaining sufficient UI to explain how to get there. Consider dark/light mode and narrow-screen readability.
4. Prefer a compact PNG/WebP; optimize file size. Add alt text and a short version note beside each screenshot.
5. **Only after the real image exists**, replace the corresponding *Screenshot pending* text in the feature page with a Markdown image link, such as `![Tracked applications list](../assets/screenshots/tracked-apps-list.png)`.
6. Verify that the image reflects the **current released or verified preview UX**; refresh screenshots when a flow changes.

**No screenshots are embedded yet.** This file is a capture backlog, not evidence that planned features are available.
