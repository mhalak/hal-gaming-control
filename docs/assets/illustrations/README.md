# Feature illustrations — HAL Systems art pack

[← Documentation hub](../../README.md) · [← Project home](../../../README.md)

The feature illustrations follow the existing SmartHouse Parental Control banner's visual direction: dark teal, cyan/bright yellow highlights, warm parent-and-child cartoon caricatures, bold outlines, and the friendly white robot.

**Artwork is a visual explanation, not a real Home Assistant screenshot.** The approved `gaming-budgets.webp` has been committed. The remaining planned files are not in the repository yet; do not add links until the actual image files are imported and verified. The characters are fictionalized cartoons, not real family photographs.

| Asset | Status | Guide | Depicts |
| --- | --- | --- | --- |
| [`gaming-budgets.webp`](gaming-budgets.webp) | **Committed** | [Gaming budgets](../../features/gaming-budgets.md) | Royal parent distributing +10 and +30 golden bonus coins to the children, with robot |
| [`gaming-budgets-portrait.webp`](gaming-budgets-portrait.webp) | **Committed** | [Gaming budgets](../../features/gaming-budgets.md) | Portrait variant for the narrower README image column; same characters and bonus coins |
| `tracked-applications.webp` | **Planned** | [Tracked applications](../../features/tracked-applications.md) | Robot displaying a grid of different app identities |
| `parent-actions.webp` | **Planned** | [Manual actions](../../features/parent-actions.md) | Parent using an explicit lock/pause control |
| `screen-idle-bonus.webp` | **Planned** | [Screen idle bonus — planned](../../features/screen-idle-bonus.md) | Sleeping child and background game continuing |
| `budget-overview.webp` | **Planned** | [Budget overview — planned](../../features/budget-overview.md) | Robot with an itemized receipt and remaining-time indicator |

## Publishing workflow

1. Import each subsequent approved WebP asset using its planned filename.
2. Confirm the file exists and renders in GitHub before linking it from the matching guide and README two-column feature card.
3. Keep a visible **Planned** marker on features that don't exist yet. Art alone is not proof of implementation.
4. Follow the separate [real screenshot checklist](../screenshots/README.md) for actual UI captures, privacy, and version labeling.

This keeps our illustration style consistent and avoids fictional UI screenshots.

## Mobile README card experiment

The gaming-budget card uses a GitHub-rendered HTML table: a **132-pixel image column** with a 120-pixel-wide portrait image, and an unbounded text column that receives remaining width. The portrait is intended for narrow portrait-mode screens; the previous landscape image remains committed for the detailed guide. GitHub strips custom CSS and does not support arbitrary media queries in a repository README, so mobile behavior must be verified on an actual phone before applying this layout to every feature.
