"""Runtime provenance is descriptive, never an inferred source revision."""
import json
import sys
from unittest.mock import patch

import pytest

from gaming_control import update_control as U
from gaming_control import mqtt_bridge as M

SHA = "a" * 40
INFO = {"release": "Preview", "component": "windows_agent", "version": "0.2.3", "commit": SHA}


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "agent.exe"))
    (tmp_path / "version.txt").write_text("0.2.3", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("info,expected", [
    (INFO, SHA), (INFO | {"version": "0.2.1"}, None),
    (INFO | {"component": "home_assistant"}, None),
    (INFO | {"commit": "abc"}, None), (INFO | {"commit": True}, None),
    (INFO | {"commit": "A" * 40}, None), (INFO | {"commit": "z" * 40}, None),
    (INFO | {"extra": "bad"}, None), ([], None),
    (INFO | {"release": ""}, None),
])
def test_packaged_build_sha(package, info, expected):
    (package / "build-info.json").write_text(json.dumps(info), encoding="utf-8")
    assert U.installed_build_sha("0.2.3") == expected


@pytest.mark.parametrize("payload", [None, "{bad", " " * 8193,
    '{"release":"Preview","component":"windows_agent","version":"0.2.3","commit":"bad","commit":"' + SHA + '"}'])
def test_missing_or_bad_provenance_is_unknown(package, payload):
    if payload is not None:
        (package / "build-info.json").write_text(payload, encoding="utf-8")
    assert U.installed_build_sha("0.2.3") is None


@pytest.mark.parametrize("sha", [SHA, None])
def test_bridge_reports_packaged_sha_or_unknown(sha):
    config = {"device": {"id": "pc1", "name": "Test PC"}, "mqtt": {"host": "broker.invalid"}}
    with patch.object(M.mqtt, "Client"), patch.object(M, "installed_version", return_value="0.2.3"), \
         patch.object(M, "installed_build_sha", return_value=sha):
        bridge = M.Bridge(config)
    assert bridge.metadata["agent_version"] == "0.2.3"
    assert bridge.metadata["agent_build_sha"] == sha
