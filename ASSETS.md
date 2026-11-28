# Artwork provenance and redistribution

The HAL Gaming Control banner and both integration icon variants are AI-generated artwork commissioned/created by the project owner using ChatGPT. The owner confirms this origin and authorizes public redistribution of these three assets as part of the source-only development preview and its MIT-licensed repository materials.

| Asset | Project purpose | Origin and redistribution |
| --- | --- | --- |
| `docs/assets/banner.png` | README banner | ChatGPT-generated; owner-authorized redistribution |
| `custom_components/hal_gaming_control/brand/icon.png` | Integration icon (256 px) | ChatGPT-generated; owner-authorized redistribution |
| `custom_components/hal_gaming_control/brand/icon@2x.png` | High-resolution integration icon (512 px) | ChatGPT-generated; owner-authorized redistribution |
| `windows_agent/gaming_control/popup_wordmark.py` (embedded PNG) | Transparent HAL Systems popup footer | Extracted from the owner-approved `docs/assets/banner.png`, Git blob `84928df45693171b68efb14a2baee552eae92cc9`; the original custom A glyph and blue dot are retained. No substitute font. |

See [LICENSE](LICENSE) for repository license terms. This record is the owner's provenance and redistribution authorization, not a representation of exclusive copyright ownership, third-party licensing, or external trademark clearance. No affiliation with Home Assistant, HACS, Microsoft or game publishers is implied.

The footer PNG is a 277 × 93 px transparent, palette-encoded crop of the original banner, with dark background and cyan divider removed and foreground colors normalized for the popup. The original image crop rectangle is `(1220, 55, 1508, 154)` in pixels. The resulting PNG SHA-256 is `3bde4089ac6236d815d47b59f367fe339f1d625fb5f9054be019d66cbd59bc11`. It is embedded in an imported Python module so frozen Windows packages have no external image lookup or network dependency.
