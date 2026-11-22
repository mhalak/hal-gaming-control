"""Mock Windows API contracts; physical SYSTEM acceptance remains separate."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import ctypes
import subprocess

import pytest

from gaming_control import focus_session as F


@pytest.mark.parametrize("sessions, console, expected", [
    ([(0, 0), (1, 1)], 1, (None, "idle")),
    ([(3, 0), (2, 0)], 3, (3, "unlocked")),
    ([(4, 0), (1, 1)], 99, (4, "unlocked")),
    ([(2, 0), (3, 0)], 99, (None, "unknown")),
])
def test_select_interactive_session(sessions, console, expected):
    api = SimpleNamespace(
        WTSActive=0,
        WTSEnumerateSessions=Mock(return_value=[
            {"SessionId": session, "State": state} for session, state in sessions]),
        WTSGetActiveConsoleSessionId=Mock(return_value=console))
    with patch.dict("sys.modules", {"win32ts": api}), \
            patch.object(F, "session_state", return_value="unlocked") as state:
        assert F.selected_session() == expected
    if expected[0] is None:
        state.assert_not_called()
    else:
        state.assert_called_once_with(expected[0])


@pytest.mark.parametrize("ok, size, level, session, state, flags, expected", [
    (False, 9999, 1, 2, 0, 1, "unknown"),
    (True, 0, 1, 2, 0, 1, "unknown"),
    (True, 9999, 2, 2, 0, 1, "unknown"),
    (True, 9999, 1, 3, 0, 1, "unknown"),
    (True, 9999, 1, 2, 1, 1, "unknown"),
    (True, 9999, 1, 2, 0, 0, "locked"),
    (True, 9999, 1, 2, 0, 1, "unlocked"),
    (True, 9999, 1, 2, 0, 7, "unknown"),
])
def test_session_state_validates_wts_response_and_frees_memory(ok, size, level, session, state, flags, expected):
    def query(_server, _session, info_class, ptr, count):
        assert info_class == 25 and _session == 2
        ptr._obj.value = 1234
        count._obj.value = size
        return ok

    api = SimpleNamespace(WTSQuerySessionInformationW=Mock(side_effect=query), WTSFreeMemory=Mock())
    value = SimpleNamespace(level=level, data=SimpleNamespace(session=session, state=state, flags=flags))
    with patch.object(ctypes, "WinDLL", return_value=api, create=True), \
            patch.object(ctypes, "cast", return_value=SimpleNamespace(contents=value)) as cast:
        assert F.session_state(2) == expected
    assert api.WTSFreeMemory.call_count == int(ok)
    if ok:
        assert api.WTSFreeMemory.call_args.args[0].value == 1234
    assert cast.call_count == int(ok and size > 0)


class WinError(Exception):
    def __init__(self, code):
        self.winerror = code


@pytest.fixture
def helper_api():
    handle = Mock()
    file = SimpleNamespace(CreateFile=Mock(return_value=handle), WriteFile=Mock())
    pipe = SimpleNamespace(GetNamedPipeServerProcessId=Mock(return_value=123))
    with patch.dict("sys.modules", {"pywintypes": SimpleNamespace(error=WinError),
                                    "win32file": file, "win32pipe": pipe}):
        yield handle, file, pipe


@pytest.mark.parametrize("name, parent", [("bad", "123"), (F.PIPE_PREFIX + "a"*32, "0"),
                                         (F.PIPE_PREFIX + "a"*32, "invalid")])
def test_helper_rejects_arguments_before_open(helper_api, name, parent):
    handle, file, _ = helper_api
    assert F.describe_exit(F.helper_main(name, parent)) == ("arguments", 0)
    file.CreateFile.assert_not_called()
    handle.Close.assert_not_called()


@pytest.mark.parametrize("stage", ["sample", "write"])
def test_helper_sends_compact_sample_and_reports_failure(helper_api, stage):
    handle, file, pipe = helper_api
    sample = {"status": "idle", "time": 10}
    if stage == "write":
        file.WriteFile.side_effect = [None, WinError(109)]
        sample_effect = [sample, sample]
    else:
        sample_effect = [sample, WinError(109)]
    with patch.object(F, "sample_window", side_effect=sample_effect), \
            patch.object(F, "read_interactive_input_idle_ms", return_value=None), \
            patch.object(F.time, "sleep") as sleep:
        code = F.helper_main(F.PIPE_PREFIX + "a"*32, "123")
    assert F.describe_exit(code) == (stage, 109)
    file.CreateFile.assert_called_once()
    pipe.GetNamedPipeServerProcessId.assert_called_once_with(handle)
    assert file.WriteFile.call_args_list[0].args == (handle, b'{"status":"idle","time":10,"last_input_idle_ms":null}')
    sleep.assert_called_once_with(F.SAMPLE_PERIOD)
    handle.Close.assert_called_once()


@pytest.mark.parametrize("wait, failure", [(258, False), (0, False), (258, True)])
def test_close_releases_handles_even_if_termination_fails(wait, failure):
    p = F.FocusProbe()
    p.pipe, p.process, p.pid, p.session = Mock(), Mock(), 123, 2
    pipe, process = p.pipe, p.process
    event = SimpleNamespace(WAIT_TIMEOUT=258, WaitForSingleObject=Mock(return_value=wait))
    api = SimpleNamespace(TerminateProcess=Mock(side_effect=OSError("synthetic") if failure else None))
    with patch.dict("sys.modules", {"win32event": event, "win32process": api}):
        p.close()
        p.close()
    pipe.Close.assert_called_once()
    process.Close.assert_called_once()
    assert api.TerminateProcess.call_count == int(wait == 258)
    assert p.pipe is p.process is p.pid is p.session is None


@pytest.mark.parametrize("frozen, fails", [(True, False), (False, False), (False, True)])
def test_start_uses_user_token_private_pipe_and_releases_token(frozen, fails):
    p = F.FocusProbe()
    token, thread, process, handle = Mock(), Mock(), Mock(), Mock()
    sa, startup = SimpleNamespace(), SimpleNamespace()
    py = SimpleNamespace(SECURITY_ATTRIBUTES=Mock(return_value=sa))
    con = SimpleNamespace(CREATE_NO_WINDOW=0x08000000, CREATE_UNICODE_ENVIRONMENT=0x400)
    pipe = SimpleNamespace(PIPE_ACCESS_INBOUND=1, PIPE_TYPE_MESSAGE=4, PIPE_READMODE_MESSAGE=2,
                           PIPE_NOWAIT=1, CreateNamedPipe=Mock(return_value=handle))
    proc = SimpleNamespace(STARTUPINFO=Mock(return_value=startup),
                           CreateProcessAsUser=Mock(return_value=(process, thread, 123, 1)))
    if fails:
        proc.CreateProcessAsUser.side_effect = OSError("synthetic launch failure")
    env = {"SYNTHETIC": "1"}
    profile = SimpleNamespace(CreateEnvironmentBlock=Mock(return_value=env))
    sid = "S-1-5-21-1-2-3-1001"
    security = SimpleNamespace(TokenUser=1, SDDL_REVISION_1=1,
        GetTokenInformation=Mock(return_value=("sid", 0)),
        ConvertSidToStringSid=Mock(return_value=sid),
        ConvertStringSecurityDescriptorToSecurityDescriptor=Mock(return_value="descriptor"))
    ts = SimpleNamespace(WTSQueryUserToken=Mock(return_value=token))
    modules = {"pywintypes": py, "win32con": con, "win32pipe": pipe, "win32process": proc,
               "win32profile": profile, "win32security": security, "win32ts": ts}
    with patch.dict("sys.modules", modules), patch.object(F.sys, "frozen", frozen, create=True), \
            patch.object(F.secrets, "token_hex", return_value="a"*32), \
            patch.object(F.os, "getpid", return_value=456), \
            patch.object(F.time, "monotonic", return_value=20):
        if fails:
            with pytest.raises(OSError, match="synthetic launch failure"):
                p._start(2)
        else:
            p._start(2)
    ts.WTSQueryUserToken.assert_called_once_with(2)
    token.Close.assert_called_once()
    security.ConvertStringSecurityDescriptorToSecurityDescriptor.assert_called_once_with(F.pipe_sddl(sid), 1)
    assert sa.bInheritHandle is False
    name = F.PIPE_PREFIX + "a"*32
    assert pipe.CreateNamedPipe.call_args.args == (name, 1 | 0x80000, 4 | 2 | 1 | 8, 1, 0, 4096, 0, sa)
    assert startup.lpDesktop == r"winsta0\default"
    profile.CreateEnvironmentBlock.assert_called_once_with(token, False)
    args = proc.CreateProcessAsUser.call_args.args
    assert args[0] is token and args[5] is False and args[6] == 0x08000400 and args[7] is env
    expected = [args[1]]
    if not frozen:
        from pathlib import Path
        expected.append(str(Path(F.__file__).resolve().parent.parent / "service_entry.py"))
    expected.extend(["--focus-helper", name, "456"])
    assert args[2] == subprocess.list2cmdline(expected)
    if fails:
        thread.Close.assert_not_called()
        assert p.process is None
    else:
        thread.Close.assert_called_once()
        assert (p.process, p.pid, p.session, p.started) == (process, 123, 2, 20)


def test_exit_query_error_is_reported_without_claiming_child_exited():
    p = F.FocusProbe()
    p.process = Mock()
    event = SimpleNamespace(WAIT_OBJECT_0=0, WaitForSingleObject=Mock(side_effect=WinError(5)))
    with patch.dict("sys.modules", {"win32event": event, "win32process": Mock()}), \
            patch.object(p, "_report_error") as report:
        assert not p._report_child_exit()
    report.assert_called_once_with("exit_query", 5)
