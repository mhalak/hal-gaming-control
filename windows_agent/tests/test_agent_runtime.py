"""Exercise the production polling loop with mocked OS and broker boundaries."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil
import pytest
import yaml

from gaming_control import agent as A

RULES = [{"name": "Game", "process": "game.exe",
          "path_contains": "/games/", "command_line_arg": "--play"}]


def process(pid, name="game.exe", exe="/games/game.exe", args=None):
    p = Mock(pid=pid)
    p.oneshot.return_value = __import__("contextlib").nullcontext()
    p.name.return_value = name
    p.exe.return_value = exe
    p.cmdline.return_value = ["--play"] if args is None else args
    p.create_time.return_value = 10
    p.is_running.return_value = True
    return p


def test_scan_filters_identity_and_transient_process_errors():
    valid = process(1, name="GAME.EXE")
    wrong_name = process(2, name="other.exe")
    wrong_path = process(3, exe="/other/game.exe")
    wrong_args = process(4, args=["--editor"])
    denied = process(5)
    denied.name.side_effect = psutil.AccessDenied(5)

    def lookup(pid):
        if pid == 6:
            raise psutil.NoSuchProcess(pid)
        return {1: valid, 2: wrong_name, 3: wrong_path, 4: wrong_args, 5: denied}[pid]

    with patch.object(A.psutil, "pids", return_value=list(range(1, 7))), \
            patch.object(A.psutil, "Process", side_effect=lookup):
        assert A.scan(RULES) == [(valid, "Game", 10)]
    wrong_name.exe.assert_not_called()
    wrong_name.cmdline.assert_not_called()
    wrong_path.create_time.assert_not_called()
    wrong_args.create_time.assert_not_called()


@pytest.mark.parametrize("change", ["dead_original", "wrong_path", "wrong_args",
                                    "dead_current", "disappeared", "denied", "oserror"])
def test_termination_rechecks_all_constraints(change):
    old, new = process(1), process(1)
    if change == "dead_original":
        old.is_running.return_value = False
    elif change == "wrong_path":
        new.exe.return_value = "/other/game.exe"
    elif change == "wrong_args":
        new.cmdline.return_value = ["--editor"]
    elif change == "dead_current":
        new.is_running.return_value = False
    elif change == "disappeared":
        new.name.side_effect = psutil.NoSuchProcess(1)
    elif change == "denied":
        new.exe.side_effect = psutil.AccessDenied(1)
    else:
        new.cmdline.side_effect = OSError("synthetic")
    with patch.object(A, "scan", return_value=[(old, "Game", 10)]), \
            patch.object(A.psutil, "Process", return_value=new):
        A.stop_games(RULES)
    new.terminate.assert_not_called()


def test_termination_allows_verified_constrained_game_only():
    old, new = process(1), process(1)
    with patch.object(A, "scan", return_value=[(old, "Game", 10)]), \
            patch.object(A.psutil, "Process", return_value=new):
        A.stop_games(RULES)
    new.terminate.assert_called_once_with()


def test_unknown_command_has_no_os_effect():
    with patch.object(A, "stop_games") as stop, patch.object(A, "lock_active_session") as lock:
        with pytest.raises(ValueError, match="Unknown command"):
            A.execute("unexpected", RULES)
    stop.assert_not_called()
    lock.assert_not_called()


def test_logging_inaccessible_executable(caplog):
    import logging
    p = process(1)
    p.exe.side_effect = psutil.AccessDenied(1)
    with caplog.at_level(logging.INFO), patch.object(A, "process_session_id", return_value=2):
        assert A.log_game_changes([(p, "Game", 10)], {}) == {(1, 10, "Game"): p}
    assert "exe=<unavailable>" in caplog.text


class Stop:
    def __init__(self, iterations=1):
        self.iterations = iterations
        self.waits = []

    def is_set(self):
        return self.iterations <= 0

    def wait(self, delay):
        self.waits.append(delay)
        self.iterations -= 1


@pytest.fixture
def runtime(tmp_path):
    config = {"games": RULES, "gaming": {"check_interval_seconds": 2}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    bridge = Mock(root="SmartHouse/Gaming/test", updates_enabled=True, last={})
    bridge.drain_commands.return_value = []
    bridge.publish.return_value = True
    bridge.client.is_connected.return_value = True
    bridge.client.publish.return_value = SimpleNamespace(rc=0)
    focus = Mock()
    focus.read.return_value = {"gaming_active": "OFF", "active_game": "idle"}
    with patch.multiple(A, Bridge=Mock(return_value=bridge), FocusProbe=Mock(return_value=focus),
                        scan=Mock(return_value=[]), system_uptime=Mock(return_value=123),
                        installed_version=Mock(return_value="1.2.3"),
                        execute=Mock(), submit_request=Mock(), confirm_health=Mock(return_value=True),
                        read_status=Mock(return_value=None)):
        yield path, bridge, focus


def test_run_advertises_os_hostname_and_preserves_generated_identity(runtime):
    path, _, _ = runtime
    with patch("gaming_control.identity.socket.gethostname", return_value="DESKTOP-LUCIJA"):
        A.run(path, Stop())
    resolved = A.Bridge.call_args.args[0]
    assert resolved["device"]["name"] == "DESKTOP-LUCIJA"
    assert resolved["device"]["id"] == (path.parent / "device_id").read_text().strip()


def test_no_catalog_starts_and_keeps_raw_foreground_telemetry(runtime):
    path, bridge, focus = runtime
    path.write_text(yaml.safe_dump({"mqtt": {"host": "broker"}}), encoding="utf-8")
    A.run(path, Stop())
    A.scan.assert_called_once_with([])
    focus.read.assert_called_once_with([])
    bridge.publish_raw_foreground.assert_called_once()
    A.execute.assert_not_called()


def test_no_catalog_rejects_manual_terminate_without_scanning():
    with patch.object(A, "stop_games") as stop:
        with pytest.raises(ValueError, match="unavailable"):
            A.execute("terminate_game", [])
    stop.assert_not_called()


def test_empty_rules_do_not_scan_process_list():
    with patch.object(A.psutil, "pids") as pids:
        assert A.scan([]) == []
    pids.assert_not_called()


def test_run_dispatches_commands_and_publishes_telemetry(runtime):
    path, bridge, focus = runtime
    request = {"request_id": "synthetic"}
    bridge.drain_commands.return_value = ["lock_pc", ("update", request), "terminate_game"]
    A.execute.side_effect = [RuntimeError("synthetic command failure"), None]
    A.read_status.return_value = '{"state":"ready"}'
    stop = Stop()
    A.run(path, stop)
    assert A.execute.call_count == 2
    A.execute.assert_any_call("lock_pc", RULES)
    A.execute.assert_any_call("terminate_game", RULES)
    A.submit_request.assert_called_once_with(path.parent, request, "1.2.3")
    focus.read.assert_called_once_with(RULES)
    bridge.publish.assert_called_once_with(
        {"in_game": "OFF", "current_game": "idle", "gaming_active": "OFF", "active_game": "idle"}, 123)
    A.confirm_health.assert_called_once_with(bridge, path.parent)
    bridge.client.publish.assert_called_once_with(
        bridge.root + "/update/status", '{"state":"ready"}', qos=1, retain=True)
    assert bridge.last["_update_status"] == '{"state":"ready"}'
    assert stop.waits == [1.0]
    bridge.start.assert_called_once()
    bridge.stop.assert_called_once()
    focus.close.assert_called_once()


@pytest.mark.parametrize("enabled,synchronized,connected", [
    (False, True, True), (True, False, True), (True, True, False),
])
def test_run_does_not_report_health_without_synchronized_connection(runtime, enabled, synchronized, connected):
    path, bridge, _ = runtime
    bridge.updates_enabled = enabled
    bridge.publish.return_value = synchronized
    bridge.client.is_connected.return_value = connected
    A.run(path, Stop())
    A.confirm_health.assert_not_called()
    A.read_status.assert_not_called()
    bridge.client.publish.assert_not_called()


def test_run_retries_failed_status_and_avoids_duplicate_success(runtime):
    path, bridge, _ = runtime
    A.confirm_health.return_value = False
    A.read_status.return_value = "status"
    bridge.client.publish.side_effect = [SimpleNamespace(rc=1), SimpleNamespace(rc=0)]
    A.run(path, Stop(3))
    assert A.confirm_health.call_count == 3
    assert bridge.client.publish.call_count == 2
    assert bridge.last["_update_status"] == "status"


def test_run_health_throttling(runtime):
    path, bridge, _ = runtime
    with patch.object(A.time, "monotonic", side_effect=[0, 0, 9, 10, 10]):
        A.run(path, Stop(3))
    assert A.confirm_health.call_count == 2


def test_run_stops_during_command_drain(runtime):
    path, bridge, focus = runtime
    stop = Stop()

    def command(_command, _rules):
        stop.iterations = 0

    A.execute.side_effect = command
    bridge.drain_commands.return_value = ["lock_pc", "terminate_game"]
    A.run(path, stop)
    A.execute.assert_called_once_with("lock_pc", RULES)
    A.scan.assert_not_called()
    focus.read.assert_not_called()
    bridge.publish.assert_not_called()
    focus.close.assert_called_once()
    bridge.stop.assert_called_once()


@pytest.mark.parametrize("failure", ["start", "publish"])
def test_run_cleanup_on_runtime_failure(runtime, failure):
    path, bridge, focus = runtime
    getattr(bridge, failure).side_effect = RuntimeError("synthetic")
    with pytest.raises(RuntimeError, match="synthetic"):
        A.run(path, Stop())
    focus.close.assert_called_once()
    bridge.stop.assert_called_once()


@pytest.mark.parametrize("interval", [0.24, 5.01])
def test_invalid_interval_rejected_before_bridge_setup(runtime, interval):
    path, bridge, focus = runtime
    path.write_text(yaml.safe_dump({"games": RULES, "gaming": {"check_interval_seconds": interval}}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="Interval"):
        A.run(path, Stop())
    A.Bridge.assert_not_called()
    A.FocusProbe.assert_not_called()


@pytest.mark.parametrize("synchronized", [True, False])
def test_run_captures_foreground_before_probe_and_publishes_only_when_synced(runtime, synchronized):
    path, bridge, focus = runtime
    bridge.updates_enabled = False
    bridge.publish.return_value = synchronized
    calls = []
    context = object()
    values = {"gaming_active": "OFF", "active_game": "idle"}
    bridge.capture_foreground_context.side_effect = lambda: calls.append("capture") or context
    focus.read.side_effect = lambda rules: calls.append("probe") or values
    bridge.publish.side_effect = lambda *args: calls.append("legacy") or synchronized
    bridge.publish_foreground.side_effect = lambda *args: calls.append("foreground")
    A.run(path, Stop())
    assert calls == ["capture", "probe", "legacy"] + (["foreground"] if synchronized else [])
    if synchronized:
        bridge.publish_foreground.assert_called_once_with(values, context)
    else:
        bridge.publish_foreground.assert_not_called()


def test_targeted_command_does_not_execute_legacy_mass_kill(runtime):
    path, bridge, _ = runtime
    path.write_text(yaml.safe_dump({"mqtt": {"host": "broker"}}), encoding="utf-8")
    offer = {"candidate": ("RobloxPlayerBeta.exe", 410, 1000.5, 3, None),
             "sample_time": 100.0, "offered_at": 101.0}
    bridge.drain_commands.return_value = [("terminate_target", offer, "e" * 32)]
    with patch.object(A, "execute_targeted", return_value=True) as target:
        A.run(path, Stop())
    target.assert_called_once_with(offer, A.FocusProbe.return_value)
    bridge.publish_target_result.assert_called_once_with("e" * 32, True)
    A.execute.assert_not_called()
    bridge.publish_target_offer.assert_called_once()


def test_targeted_execution_requires_new_user_foreground_sample():
    offer = {"candidate": ("RobloxPlayerBeta.exe", 410, 1000.5, 3, None),
             "sample_time": 100.0, "offered_at": 101.0}
    focus = Mock(candidate=offer["candidate"], last_sample_time=102.0)
    with patch.object(A, "selected_session", return_value=(3, "unlocked")), \
         patch.object(A, "terminate_verified", return_value=True) as verified, \
         patch.object(A.time, "monotonic", return_value=102.1):
        assert A.execute_targeted(offer, focus)
    focus.read.assert_called_once_with([])
    assert verified.call_args.kwargs["current_sample"] == 102.0
    assert verified.call_args.kwargs["session"] == (3, "unlocked")


def test_targeted_execution_requires_sample_after_command_receipt():
    offer = {"candidate": ("RobloxPlayerBeta.exe", 410, 1000.5, 3, None),
             "sample_time": 100.0, "offered_at": 101.0, "received_at": 102.0}
    focus = Mock(candidate=offer["candidate"], last_sample_time=101.5)
    with patch.object(A, "selected_session", return_value=(3, "unlocked")), \
         patch.object(A, "terminate_verified", return_value=False) as verify, \
         patch.object(A.time, "monotonic", return_value=102.3):
        assert not A.execute_targeted(offer, focus)
    assert verify.call_args.kwargs["offered_sample"] == 102.0
    assert verify.call_args.kwargs["current_sample"] == 101.5
