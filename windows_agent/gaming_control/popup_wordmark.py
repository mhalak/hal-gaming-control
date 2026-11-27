"""Embedded transparent PNG derived from the approved HAL Systems banner.

Source: docs/assets/banner.png (Git blob 84928df45693171b68efb14a2baee552eae92cc9).
Crop (1220, 55, 1508, 154); isolate original glyphs and blue dot from the
dark background and cyan divider, normalize foreground colors and trim.
277 x 93 px, alpha palette; no fonts, network, or external resource path.
PNG SHA-256: 3bde4089ac6236d815d47b59f367fe339f1d625fb5f9054be019d66cbd59bc11.
Imported normally by the renderer, so frozen Windows builds include it.
"""

WORDMARK_PNG_BASE64 = (
    "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"
)


def wordmark_image(tk, root):
    """Scale the same embedded image while preserving its aspect ratio."""
    source = tk.PhotoImage(master=root, data=WORDMARK_PNG_BASE64, format="png")
    scale = float(root.tk.call("tk", "scaling")) * 72 / 96
    if scale >= 1.75:
        return source.zoom(2, 2).subsample(3, 3)
    if scale >= 1.125:
        return source.subsample(2, 2)
    return source.subsample(3, 3)
