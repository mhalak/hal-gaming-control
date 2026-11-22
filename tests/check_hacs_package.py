"""Offline checks for HACS packaging; official validation is separate."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
components = root / "custom_components"
domains = [p.name for p in components.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__"]
assert domains == ["hal_gaming_control"], domains
for legacy in ("smarthouse_gaming", "parental", "parental_control"):
    assert not (components / legacy).exists(), legacy
integration = components / domains[0]
manifest = json.loads((integration / "manifest.json").read_text())
hacs = json.loads((root / "hacs.json").read_text())
assert manifest["domain"] == integration.name
assert all(manifest.get(k) for k in ("documentation", "issue_tracker", "codeowners", "name", "version"))
assert manifest["name"] == hacs["name"]
assert manifest["documentation"] == "https://github.com/mhalak/hal-gaming-control" and manifest["issue_tracker"] == "https://github.com/mhalak/hal-gaming-control/issues"
assert set(hacs) <= {"name", "homeassistant", "hacs", "content_in_root", "zip_release", "filename", "hide_default_branch", "country", "persistent_directory", "render_readme"}
assert (integration / "__init__.py").is_file()
assert (integration / "brand/icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
assert (root / "README.md").is_file()
assert hacs.get("render_readme") is True or (root / "info.md").is_file()
assert (root / "LICENSE").is_file()
assert (root / "docs/windows_deployment.md").is_file()
assert json.loads((integration / "strings.json").read_text()) == json.loads((integration / "translations/en.json").read_text())
# Prevent regressions caught by the official hassfest validator.
expected_manifest_keys = ["domain", "name"] + sorted(set(manifest) - {"domain", "name"})
assert list(manifest) == expected_manifest_keys, "Manifest keys must start with domain, name, then alphabetical order"


def translation_html_paths(value, path=""):
    """Find HTML-like tags in translation values, including angle-bracket placeholders."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from translation_html_paths(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from translation_html_paths(child, f"{path}[{index}]")
    elif isinstance(value, str) and re.search(r"</?[A-Za-z][^<>]*>", value):
        yield path


for relative_path in ("strings.json", "translations/en.json"):
    translations = json.loads((integration / relative_path).read_text())
    invalid_paths = list(translation_html_paths(translations))
    assert not invalid_paths, f"{relative_path}: HTML-like tags in {invalid_paths}"

print("HACS package structural checks passed")
