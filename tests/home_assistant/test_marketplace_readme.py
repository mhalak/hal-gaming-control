"""Marketplace landing page should describe Local Mode once, in its first card."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_mode_has_one_feature_card_without_repeated_intro():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count('<a name="feature-local-mode"></a>') == 1
    assert readme.count("<h3>🏠 100% local") == 1
    assert "**🏠 Local-first. Your home, your data.**" not in readme
    first_feature = readme.index('<a name="feature-local-mode"></a>')
    next_feature = readme.index('<a name="feature-gaming-budgets"></a>')
    assert first_feature < next_feature
    assert readme.count("How local mode works</a>") == 1
    assert (ROOT / "docs/features/local-mode.md").is_file()
