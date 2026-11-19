"""Opt-in physical Windows regression; run under SYSTEM with a standard user logged in."""
import os
from pathlib import Path
import sys
import time
import pytest

EXE = os.environ.get("SMARTHOUSE_FOCUS_SYSTEM_TEST_EXE")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not EXE,
                                reason="Requires authorized real SYSTEM/interactive-user packaged EXE test")


def test_real_system_to_user_pipe(monkeypatch):
    import win32api
    import win32con
    import win32security
    import win32ts
    from gaming_control.focus_session import FocusProbe, selected_session, MAX_SAMPLE_AGE

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(
            token, win32security.TokenUser)[0])
        assert sid == "S-1-5-18", "Test must run as LocalSystem"
    finally:
        token.Close()
    session, state = selected_session()
    assert session and state == "unlocked", "Require unlocked interactive session"
    token = win32ts.WTSQueryUserToken(session)
    try:
        assert not win32security.GetTokenInformation(token, win32security.TokenElevation), (
            "Require non-elevated interactive user")
    finally:
        token.Close()
    exe = Path(EXE)
    assert exe.is_absolute() and exe.is_file()
    probe = FocusProbe()
    try:
        with monkeypatch.context() as m:
            m.setattr(sys, "executable", str(exe))
            m.setattr(sys, "frozen", True, raising=False)
            probe._start(session)
        samples = 0
        usable = 0
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and samples < 8:
            assert not probe._report_child_exit(), "Packaged helper exited; inspect logged stage/code"
            sample = probe._receive()
            if sample is not None:
                assert 0 <= time.monotonic() - sample["time"] <= MAX_SAMPLE_AGE
                assert sample["status"] in ("window", "idle", "unknown")
                samples += 1
                usable += sample["status"] in ("window", "idle")
            time.sleep(.25)
        assert samples == 8, "Expected eight fresh samples over authenticated IPC"
        assert usable > 0, "IPC works but no usable foreground observation was obtained"
    finally:
        probe.close()
