"""Unit regression for the exact ACL and safe helper diagnostics."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import re
from gaming_control.focus_session import (
    FocusProbe, PIPE_PREFIX, PIPE_USER_ACCESS, helper_main, helper_error,
    describe_exit, pipe_sddl,
)


class WinError(Exception):
    def __init__(self, code):
        self.winerror = code
        super().__init__("sensitive diagnostic details must not be surfaced")


def test_exact_user_access_mask_and_scope():
    sid = "S-1-5-21-1-2-3-1001"
    assert PIPE_USER_ACCESS == 0x00120196
    assert pipe_sddl(sid) == f"D:P(A;;GA;;;SY)(A;;0x00120196;;;{sid})"


def test_open_denial_is_nonzero_and_identifies_stage():
    file = SimpleNamespace(CreateFile=Mock(side_effect=WinError(5)))
    with patch.dict("sys.modules", {"pywintypes": SimpleNamespace(error=WinError),
                                    "win32file": file, "win32pipe": Mock()}):
        code = helper_main(PIPE_PREFIX + "a"*32, "123")
    assert code != 0
    assert describe_exit(code) == ("open", 5)


def test_identity_mismatch_still_rejected():
    handle = Mock()
    file = SimpleNamespace(CreateFile=Mock(return_value=handle))
    pipe = SimpleNamespace(GetNamedPipeServerProcessId=Mock(return_value=999))
    with patch.dict("sys.modules", {"pywintypes": SimpleNamespace(error=WinError),
                                    "win32file": file, "win32pipe": pipe}):
        code = helper_main(PIPE_PREFIX + "a"*32, "123")
    assert describe_exit(code) == ("server_identity", 0)
    handle.Close.assert_called_once()


def test_parent_diagnostic_is_throttled(caplog):
    p = FocusProbe()
    p.process = Mock()
    event = SimpleNamespace(WAIT_OBJECT_0=0, WaitForSingleObject=Mock(return_value=0))
    process = SimpleNamespace(GetExitCodeProcess=Mock(return_value=helper_error(2, WinError(5))))
    with patch.dict("sys.modules", {"win32event":event,"win32process":process}), \
         patch("gaming_control.focus_session.time.monotonic", side_effect=[100,101,131]):
        assert p._report_child_exit()
        assert p._report_child_exit()
        assert p._report_child_exit()
    assert caplog.text.count("stage=open error_code=5") == 2
    assert "sensitive diagnostic" not in caplog.text
