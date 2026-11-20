"""Windows primitives: test the OS boundary without locking any workstation."""
import ctypes
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gaming_control import windows as W


def test_system_uptime_uses_system_ticks_and_truncates():
    ticks = Mock(return_value=123456789)
    library = SimpleNamespace(GetTickCount64=ticks)
    with patch.object(ctypes, "WinDLL", return_value=library, create=True) as dll:
        assert W.system_uptime() == 123456
    dll.assert_called_once_with("kernel32")
    ticks.assert_called_once_with()
    assert ticks.restype is ctypes.c_ulonglong
    assert ticks.argtypes == []


@pytest.mark.parametrize("ok, expected", [(True, 7), (False, None)])
def test_process_session_id_uses_output_only_on_success(ok, expected):
    def query(pid, result):
        assert pid == 123
        result._obj.value = 7
        return ok

    api = SimpleNamespace(ProcessIdToSessionId=Mock(side_effect=query))
    with patch.object(ctypes, "WinDLL", return_value=api, create=True):
        assert W.process_session_id(123) == expected


@pytest.mark.parametrize("failure", [AttributeError, OSError, ValueError])
def test_process_session_query_failure_returns_none(failure):
    with patch.object(ctypes, "WinDLL", side_effect=failure("synthetic"), create=True):
        assert W.process_session_id(123) is None


@pytest.mark.parametrize("accepted, code", [(1, 0), (0, 1)])
def test_interactive_lock_helper_exit_code(accepted, code):
    lock = Mock(return_value=accepted)
    with patch.object(ctypes, "WinDLL", return_value=SimpleNamespace(LockWorkStation=lock),
                      create=True) as dll:
        assert W.lock_this_session() == code
    dll.assert_called_once_with("user32", use_last_error=True)
    lock.assert_called_once_with()
    assert lock.argtypes == []
    assert lock.restype is ctypes.c_int


@pytest.mark.parametrize("sessions, console, expected", [
    ([(0, 0), (3, 1)], 0, None),
    ([(3, 0), (2, 0)], 3, 3),
    ([(4, 0), (3, 1)], 99, 4),
    ([(3, 0), (4, 0)], 99, None),
])
def test_session_selection_avoids_ambiguous_or_noninteractive_sessions(sessions, console, expected):
    rows = [{"SessionId": sid, "State": state} for sid, state in sessions]
    assert W.select_session(rows, console, 0) == expected


@pytest.fixture
def lock_api():
    token, process, thread = Mock(), Mock(), Mock()
    startup = SimpleNamespace()
    env = {"SYNTHETIC": "1"}
    con = SimpleNamespace(CREATE_NO_WINDOW=0x08000000, CREATE_UNICODE_ENVIRONMENT=0x400)
    event = SimpleNamespace(WAIT_OBJECT_0=0, WaitForSingleObject=Mock(return_value=0))
    proc = SimpleNamespace(STARTUPINFO=Mock(return_value=startup),
                           CreateProcessAsUser=Mock(return_value=(process, thread, 123, 1)),
                           GetExitCodeProcess=Mock(return_value=0))
    profile = SimpleNamespace(CreateEnvironmentBlock=Mock(return_value=env))
    ts = SimpleNamespace(WTSActive=0, WTSEnumerateSessions=Mock(return_value=[
        {"SessionId": 3, "State": 0}]), WTSGetActiveConsoleSessionId=Mock(return_value=3),
        WTSQueryUserToken=Mock(return_value=token))
    modules = {"win32con": con, "win32event": event, "win32process": proc,
               "win32profile": profile, "win32ts": ts}
    with patch.dict("sys.modules", modules):
        yield SimpleNamespace(token=token, process=process, thread=thread,
                              startup=startup, env=env, event=event, proc=proc,
                              profile=profile, ts=ts)


def test_ambiguous_session_never_launches_lock_helper(lock_api, caplog):
    lock_api.ts.WTSEnumerateSessions.return_value = [{"SessionId": s, "State": 0} for s in (2, 3)]
    lock_api.ts.WTSGetActiveConsoleSessionId.return_value = 99
    W.lock_active_session()
    lock_api.ts.WTSQueryUserToken.assert_not_called()
    lock_api.proc.CreateProcessAsUser.assert_not_called()
    assert "no unambiguous active interactive session" in caplog.text


@pytest.mark.parametrize("frozen, wait, code, message", [
    (True, 0, 0, "Lock request initiated"),
    (False, 0, 1, "LockWorkStation did not accept"),
    (True, 258, 0, "did not complete within five seconds"),
])
def test_lock_helper_fixed_arguments_user_token_and_cleanup(lock_api, caplog, frozen, wait, code, message):
    import logging
    a = lock_api
    a.event.WaitForSingleObject.return_value = wait
    a.proc.GetExitCodeProcess.return_value = code
    with patch.object(W.sys, "frozen", frozen, create=True), caplog.at_level(logging.INFO):
        W.lock_active_session()
    a.ts.WTSQueryUserToken.assert_called_once_with(3)
    a.profile.CreateEnvironmentBlock.assert_called_once_with(a.token, False)
    executable = str(Path(W.sys.executable).resolve())
    args = [executable]
    if not frozen:
        args.append(str(Path(W.__file__).resolve().parent.parent / "service_entry.py"))
    args.append("--lock-session")
    assert a.startup.lpDesktop == r"winsta0\default"
    a.proc.CreateProcessAsUser.assert_called_once_with(
        a.token, executable, subprocess.list2cmdline(args), None, None, False,
        0x08000400, a.env, str(Path(executable).parent), a.startup)
    a.event.WaitForSingleObject.assert_called_once_with(a.process, 5000)
    assert a.proc.GetExitCodeProcess.call_count == int(wait == 0)
    a.thread.Close.assert_called_once()
    a.process.Close.assert_called_once()
    a.token.Close.assert_called_once()
    assert message in caplog.text


@pytest.mark.parametrize("stage", ["environment", "launch", "wait"])
def test_lock_helper_releases_acquired_handles_on_failure(lock_api, stage):
    a = lock_api
    operation = {"environment": a.profile.CreateEnvironmentBlock,
                 "launch": a.proc.CreateProcessAsUser,
                 "wait": a.event.WaitForSingleObject}[stage]
    operation.side_effect = OSError("synthetic")
    with pytest.raises(OSError, match="synthetic"):
        W.lock_active_session()
    a.token.Close.assert_called_once()
    assert a.process.Close.call_count == int(stage == "wait")
    assert a.thread.Close.call_count == int(stage == "wait")
