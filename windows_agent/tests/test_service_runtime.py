"""Exercise SCM lifecycle and entry-point dispatch against fake Windows APIs."""
import importlib.util
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gaming_control import agent, focus_session, windows

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def service_module(tmp_path):
    class Framework:
        def __init__(self, args):
            self.framework_args = args
            self.ReportServiceStatus = Mock()

    manager = Mock()
    scm = SimpleNamespace(SERVICE_STOP_PENDING=3)
    util = SimpleNamespace(ServiceFramework=Framework)
    modules = {"servicemanager": manager, "win32service": scm, "win32serviceutil": util}
    spec = importlib.util.spec_from_file_location(
        "gaming_control._service_test", ROOT / "gaming_control" / "service.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", modules), patch.dict("os.environ", {"ProgramData": str(tmp_path)}):
        spec.loader.exec_module(module)
        with patch.object(module, "RotatingFileHandler") as handler, \
                patch.object(module.logging, "basicConfig") as logging_config, \
                patch.object(module, "run") as run:
            yield module, manager, handler, logging_config, run


def test_service_stop_reports_pending_and_signals_event(service_module):
    module, _, _, _, _ = service_module
    args = ["service"]
    service = module.GamingService(args)
    assert service.framework_args is args
    assert not service.stop_event.is_set()
    service.SvcStop()
    service.ReportServiceStatus.assert_called_once_with(3)
    assert service.stop_event.is_set()


@pytest.mark.parametrize("failure", [False, True])
def test_service_runs_with_rotating_log_and_reports_failure(service_module, tmp_path, failure):
    module, manager, handler, logging_config, run = service_module
    service = module.GamingService([])
    config = tmp_path / "SmartHouseGamingControl"
    assert module.CONFIG_DIR == config
    if failure:
        run.side_effect = RuntimeError("synthetic")
        with pytest.raises(RuntimeError, match="synthetic"):
            service.SvcDoRun()
        manager.LogErrorMsg.assert_called_once_with("SmartHouse Gaming Control failed; see service.log")
    else:
        service.SvcDoRun()
        manager.LogErrorMsg.assert_not_called()
    handler.assert_called_once_with(config / "service.log", maxBytes=2_000_000, backupCount=2)
    assert logging_config.call_args.kwargs["handlers"] == [handler.return_value]
    run.assert_called_once_with(config / "config.yaml", service.stop_event)


@pytest.mark.parametrize("args, code", [(["--lock-session"], 1), (["--focus-helper", "pipe", "123"], 7)])
def test_entry_point_dispatches_helpers_without_service_host(args, code):
    manager = Mock()
    util = Mock()
    with patch.dict("sys.modules", {"servicemanager": manager, "win32serviceutil": util}), \
            patch("sys.argv", ["service_entry.py"] + args), \
            patch.object(windows, "lock_this_session", return_value=1) as lock, \
            patch.object(focus_session, "helper_main", return_value=7) as focus:
        with pytest.raises(SystemExit) as error:
            runpy.run_path(str(ROOT / "service_entry.py"), run_name="__main__")
    assert error.value.code == code
    if args[0] == "--lock-session":
        lock.assert_called_once_with()
        focus.assert_not_called()
    else:
        focus.assert_called_once_with("pipe", "123")
        lock.assert_not_called()
    manager.Initialize.assert_not_called()
    util.HandleCommandLine.assert_not_called()


@pytest.mark.parametrize("args", [[], ["install"], ["--focus-helper", "incomplete"]])
def test_entry_point_service_host_or_command_line(args):
    manager = Mock()
    util = Mock()
    service = Mock()
    modules = {"servicemanager": manager, "win32serviceutil": util,
               "gaming_control.service": SimpleNamespace(GamingService=service)}
    with patch.dict("sys.modules", modules), patch("sys.argv", ["service_entry.py"] + args), \
            patch.object(windows, "lock_this_session") as lock, \
            patch.object(focus_session, "helper_main") as focus:
        runpy.run_path(str(ROOT / "service_entry.py"), run_name="__main__")
    lock.assert_not_called()
    focus.assert_not_called()
    if args:
        util.HandleCommandLine.assert_called_once_with(service)
        manager.Initialize.assert_not_called()
    else:
        manager.Initialize.assert_called_once_with()
        manager.PrepareToHostSingle.assert_called_once_with(service)
        manager.StartServiceCtrlDispatcher.assert_called_once_with()
        util.HandleCommandLine.assert_not_called()
