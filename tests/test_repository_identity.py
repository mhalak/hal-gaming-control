"""Repository and product identity contract (issue #146 follow-up).

The GitHub repository is ``mhalak/hal-gaming-control`` and the public product
name is **HAL Gaming Control**. The previous repository slug and product name
may survive only in explicitly historical documents. There are deliberately no
compatibility aliases in source code; HA domain, MQTT root and wire identifiers
are covered by tests/home_assistant/test_domain_clean_cut.py.
"""
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "mhalak/hal-gaming-control"
PRODUCT = "HAL Gaming Control"
# Built from parts so that this contract file does not itself contain the old names.
OLD_SLUG = "smarthouse" + "-parental-control"
OLD_PRODUCT = re.compile(r"Parental [Cc]ontrol")

# Documents where the previous name is part of the recorded history or is the
# name an operator will still see on an old HA entry that must be removed.
HISTORICAL_DOCUMENTS = {
    "docs/domain-clean-cut.md": "migration: old HA entries/repository name an operator must recognise",
    "docs/ha_releases.md": "HA release-note history (0.5.x / 0.6.x preview names)",
    "docs/foreground_migration.md": "historical foreground cutover record (issue #4 / #67)",
    "docs/reference/known_limitations_history.md": "archived known-limitations snapshot",
}
# The old slug is only explained in the clean-cut document (rename note).
OLD_SLUG_ALLOWED = {"docs/domain-clean-cut.md"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def text_files():
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(directory) / name
            try:
                yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary artwork etc.


def test_historical_allow_list_has_no_stale_entries():
    for relative in HISTORICAL_DOCUMENTS:
        assert (ROOT / relative).is_file(), relative
    assert OLD_SLUG_ALLOWED <= set(HISTORICAL_DOCUMENTS)


def test_old_repository_slug_only_in_the_explicit_rename_note():
    offenders = sorted(name for name, text in text_files()
                       if OLD_SLUG in text.lower() and name not in OLD_SLUG_ALLOWED)
    assert offenders == []


def test_old_product_name_only_in_historical_documents():
    offenders = sorted(name for name, text in text_files()
                       if OLD_PRODUCT.search(text) and name not in HISTORICAL_DOCUMENTS)
    assert offenders == []


def test_all_owner_repository_links_target_the_current_repository():
    link = re.compile(r"(?:github\.com|raw\.githubusercontent\.com)/mhalak/([A-Za-z0-9._-]+)")
    bad = sorted({f"{name}: {slug}" for name, text in text_files()
                  for slug in link.findall(text) if slug != "hal-gaming-control"})
    assert bad == []


def test_public_product_name_in_hacs_manifest_and_release_label():
    manifest = json.loads((ROOT / "custom_components/hal_gaming_control/manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
    assert manifest["name"] == hacs["name"] == PRODUCT
    assert manifest["documentation"] == f"https://github.com/{REPOSITORY}"
    assert manifest["issue_tracker"] == f"https://github.com/{REPOSITORY}/issues"
    assert re.fullmatch(re.escape(PRODUCT) + r" Preview [0-9]+", release["release"])
    assert manifest["domain"] == "hal_gaming_control"


def test_readme_and_ui_strings_use_the_product_name():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.splitlines()[2] == f"# {PRODUCT}"
    for relative in ("strings.json", "translations/en.json"):
        strings = json.loads((ROOT / "custom_components/hal_gaming_control" / relative).read_text(encoding="utf-8"))
        assert strings["options"]["step"]["settings_menu"]["title"] == PRODUCT
