"""Offline checks for HACS packaging; official validation is separate."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
components = root / "custom_components"
domains = [p.name for p in components.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__"]
assert domains == ["smarthouse_gaming"], domains
integration = components / domains[0]
manifest = json.loads((integration / "manifest.json").read_text())
hacs = json.loads((root / "hacs.json").read_text())
assert manifest["domain"] == integration.name
assert all(manifest.get(k) for k in ("documentation", "issue_tracker", "codeowners", "name", "version"))
assert manifest["name"] == hacs["name"]
assert set(hacs) <= {"name", "homeassistant", "hacs", "content_in_root", "zip_release", "filename", "hide_default_branch", "country", "persistent_directory", "render_readme"}
assert (integration / "__init__.py").is_file()
assert (integration / "brand/icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
assert (root / "README.md").is_file()
assert hacs.get("render_readme") is True or (root / "info.md").is_file()
assert (root / "LICENSE").is_file()
assert (root / "docs/windows_deployment.md").is_file()
assert json.loads((integration / "strings.json").read_text()) == json.loads((integration / "translations/en.json").read_text())
print("HACS package structural checks passed")
