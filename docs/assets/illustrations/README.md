# Feature illustrations — HAL Systems art pack

[← Documentation hub](../../README.md) · [← Project home](../../../README.md)

The feature illustrations follow the existing SmartHouse Parental Control banner's visual direction: dark teal, cyan/bright yellow highlights, warm parent-and-child cartoon caricatures, bold outlines, and the friendly white robot.

**Artwork is a visual explanation, not a real Home Assistant screenshot.** All five approved feature illustrations are committed and linked from the README and their guides. **Planned** describes the status of some software features, not missing artwork. Characters are fictionalized cartoons, not real family photographs.

| Asset | Status | Guide | Depicts |
| --- | --- | --- | --- |
| [`gaming-budgets.webp`](gaming-budgets.webp) | **Committed** | [Gaming budgets](../../features/gaming-budgets.md) | Royal parent distributing +10 and +30 golden bonus coins to the children, with robot |
| [`gaming-budgets-portrait.webp`](gaming-budgets-portrait.webp) | **Committed** | [Gaming budgets](../../features/gaming-budgets.md) | Portrait variant for the narrower README image column; same characters and bonus coins |
| [`tracked-applications.webp`](tracked-applications.webp) | **Committed** | [Tracked applications](../../features/tracked-applications.md) | Dad with HA tablet, girl playing Roblox, friendly robot; tablet slider is conceptual art |
| [`parent-actions.webp`](parent-actions.webp) | **Committed** | [Controls & automations](../../features/parent-actions.md) | Dad pushes robot toward two upset children, mum watches, Automation Rules! wall sign |
| [`screen-idle-bonus.webp`](screen-idle-bonus.webp) | **Committed** | [Screen idle bonus — planned](../../features/screen-idle-bonus.md) | Sleeping child, PC grinding, dad checking time while robot wags finger |
| [`budget-overview.webp`](budget-overview.webp) | **Committed** | [Budget overview — planned](../../features/budget-overview.md) | Dad auditing an itemized gaming budget; unimpressed mum and DO NOT DISTURB sign |

## Publishing workflow

1. When adding future illustrations, import each approved WebP asset using its planned filename.
2. Confirm the file exists and renders in GitHub before linking it from the matching guide and README two-column feature card.
3. Keep a visible **Planned** marker on features that don't exist yet. Art alone is not proof of implementation.
4. Follow the separate [real screenshot checklist](../screenshots/README.md) for actual UI captures, privacy, and version labeling.

This keeps our illustration style consistent and avoids fictional UI screenshots.

## Mobile README card experiment

The gaming-budget card uses a GitHub-rendered HTML table: a **132-pixel image column** with a 120-pixel-wide portrait image, and an unbounded text column that receives remaining width. The portrait is intended for narrow portrait-mode screens; the previous landscape image remains committed for the detailed guide. GitHub strips custom CSS and does not support arbitrary media queries in a repository README, so mobile behavior must be verified on an actual phone before applying this layout to every feature.
