"""Mock actual Win32 named-pipe / CreateProcessAsUser calls at the OS boundary."""
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gaming_control.popup_session import PopupSession
from gaming_control.popup_protocol import make_event


class WinError(Exception):
    def __init__(self, code):
        self.winerror = code
        super().__init__(f"Win32 error {code}")


def packet(*, operation="upsert"):
    p = {"version":1, "device_id":"pc1","producer_epoch":"a"*32,
         "sequence":1,"issued_at":int(time.time()),
         "message_ttl_seconds":15,"display_stale_after_seconds":120,
         "popup_id":"b"*32,"operation":operation}
    if operation=="upsert":
        p["view"]={"heading":"Gaming time remaining","description":"Weekly budget",
                   "remaining_seconds":598,"progress_percent":24,"buttons":[
                       {"id":"ok","text":"OK","color":"neutral"}]}
    return p


def fake_winapi():
    handle, process, thread = Mock(), Mock(), Mock()
    token = Mock()
    win32pipe = Mock(PIPE_ACCESS_DUPLEX=3, PIPE_TYPE_MESSAGE=4,
                     PIPE_READMODE_MESSAGE=2, PIPE_NOWAIT=1)
    win32pipe.CreateNamedPipe.return_value = handle
    win32pipe.GetNamedPipeClientProcessId.return_value = 345
    win32process = Mock(STARTUPINFO=Mock(return_value=SimpleNamespace(lpDesktop=None)),
                        CreateProcessAsUser=Mock(return_value=(process, thread, 345, 0)),
                        TerminateProcess=Mock(),
                        GetExitCodeProcess=Mock())
    win32ts = Mock(WTSQueryUserToken=Mock(return_value=token))
    win32security = Mock(
        TokenUser=1, SDDL_REVISION_1=1,
        GetTokenInformation=Mock(return_value=("S-1-5-21-1-2-3-1001",)),
        ConvertSidToStringSid=Mock(return_value="S-1-5-21-1-2-3-1001"),
        ConvertStringSecurityDescriptorToSecurityDescriptor=Mock(return_value="protected-acl"))
    win32profile = Mock(CreateEnvironmentBlock=Mock(return_value={}))
    win32con = Mock(CREATE_NO_WINDOW=0x08000000,
                    CREATE_UNICODE_ENVIRONMENT=0x00000400)
    attrs = SimpleNamespace(SECURITY_DESCRIPTOR=None, bInheritHandle=None)
    pywintypes = SimpleNamespace(
        SECURITY_ATTRIBUTES=lambda: attrs, error=WinError)
    win32event = SimpleNamespace(
        WAIT_TIMEOUT=258, WAIT_OBJECT_0=0,
        WaitForSingleObject=Mock(return_value=258))
    modules={
        "win32pipe":win32pipe,"win32file":Mock(),
        "win32process":win32process,"win32ts":win32ts,
        "win32profile":win32profile,"win32security":win32security,
        "win32con":win32con,"pywintypes":pywintypes,
        "win32event":win32event,
    }
    return SimpleNamespace(
        modules=modules, pipe=win32pipe, file=modules["win32file"],
        process=win32process, win32event=win32event, attrs=attrs,
        handle=handle, token=token, child=process, thread=thread)


def test_real_launch_path_is_fixed_bounded_and_runs_as_selected_user():
    win = fake_winapi()
    session = PopupSession()
    session.handle(packet(), "pc1")
    with patch.dict(sys.modules, win.modules):
        session._start(3)
        assert session.session == 3
        assert session.pid == 345
        assert session.pipe is win.handle
        assert session.process is win.child
        assert session.started > 0
        assert win.attrs.SECURITY_DESCRIPTOR == "protected-acl"
        assert win.attrs.bInheritHandle is False
        args = win.process.CreateProcessAsUser.call_args.args
        assert "--popup-helper" in args[2]
        assert "pc1" in args[2]
        assert "winsta0\\default" == args[-1].lpDesktop
        win.thread.Close.assert_called_once()
        win.token.Close.assert_called_once()
        # Closing also terminates the child, never leaves a SYSTEM window.
        session.close()
        win.process.TerminateProcess.assert_called_once_with(win.child, 0)
        win.child.Close.assert_called_once()
        win.handle.Close.assert_called_once()


def test_named_pipe_connect_checks_helper_pid_and_user_session():
    win=fake_winapi()
    session=PopupSession()
    session.pipe=win.handle
    session.pid=345
    session.session=3
    with patch.dict(sys.modules,win.modules), \
         patch("gaming_control.popup_session.process_session_id",return_value=3):
        assert session._connect()
        win.pipe.GetNamedPipeClientProcessId.return_value=999
        with pytest.raises(ValueError,match="PID"):
            session._connect()
        win.pipe.GetNamedPipeClientProcessId.return_value=345
    with patch.dict(sys.modules,win.modules), \
         patch("gaming_control.popup_session.process_session_id",return_value=4):
        with pytest.raises(ValueError,match="session"):
            session._connect()
    win.pipe.ConnectNamedPipe.side_effect=WinError(536)
    with patch.dict(sys.modules,win.modules):
        assert session._connect() is False
    win.pipe.ConnectNamedPipe.side_effect=WinError(535)
    with patch.dict(sys.modules,win.modules), \
         patch("gaming_control.popup_session.process_session_id",return_value=3):
        assert session._connect()


def test_pipe_writes_validated_current_ha_view_and_filters_stale():
    win=fake_winapi()
    session=PopupSession()
    session.handle(packet(),"pc1")
    session.pipe=win.handle
    win.file.WriteFile.return_value=(0, 100)
    with patch.dict(sys.modules,win.modules):
        session._flush()
        body=json.loads(win.file.WriteFile.call_args.args[1])
        assert body["operation"]=="upsert"
        assert session.pending is None
        session.pending=body|{"issued_at":0}
        session._flush()
        assert session.pending is None
        assert win.file.WriteFile.call_count == 1


def test_service_only_accepts_current_popup_response_and_filters_duplicates():
    win=fake_winapi()
    session=PopupSession()
    session.handle(packet(),"pc1")
    session.pipe=win.handle
    click=make_event("pc1", "b"*32, "c"*32, "button", "ok")
    wrong=click|{"button_id":"grant"}
    records=[json.dumps(wrong).encode(), json.dumps(click).encode(),
             json.dumps(click).encode(), b'{"kind":"garbage"}']
    bridge=Mock(id="pc1")

    def peek(*_args):
        return (None,len(records[0]),None) if records else (None,0,None)

    def read(*_args):
        return 0, records.pop(0)

    win.pipe.PeekNamedPipe.side_effect=peek
    win.file.ReadFile.side_effect=read
    with patch.dict(sys.modules,win.modules):
        session._events(bridge)
    bridge.publish_popup_event.assert_called_once_with(click)
    assert session.seen_events==["c"*32]


def test_exited_popup_does_not_auto_reopen_without_new_ha_command():
    win=fake_winapi()
    session=PopupSession()
    session.handle(packet(),"pc1")
    session.pipe=win.handle
    session.process=win.child
    session.pid=345
    session.session=3
    bridge=Mock(connected=True,id="pc1")
    win.win32event.WaitForSingleObject.return_value=win.win32event.WAIT_OBJECT_0
    with patch.dict(sys.modules,win.modules), \
         patch("gaming_control.popup_session.selected_session",return_value=(3,"unlocked")):
        session.pump(bridge)
    assert session.packet is None
    assert session.pending is None
    assert session.process is None
    assert session.retry_after > 0
