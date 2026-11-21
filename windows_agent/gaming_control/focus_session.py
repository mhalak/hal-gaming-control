"""Windows session-0 to interactive-desktop foreground probe.

Private, local, single-instance named pipe. The service verifies the actual
pipe client PID against the child it launched and independently validates
process identity/session. A stale/dead/malformed helper never means active.
"""
import ctypes
import json
import logging
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from .foreground import classify, candidate_from_sample, sample_window, IDLE, UNKNOWN, MAX_SAMPLE_AGE
from .windows import process_session_id

LOG = logging.getLogger(__name__)
PIPE_PREFIX = r"\\.\pipe\SmartHouseGamingFocus-"
SAMPLE_PERIOD = .25
# FILE_GENERIC_WRITE (the existing GW ACE) plus FILE_READ_ATTRIBUTES.
# GetNamedPipeServerProcessId needs the latter for this pipe client handle.
FILE_GENERIC_WRITE = 0x00120116
FILE_READ_ATTRIBUTES = 0x00000080
PIPE_USER_ACCESS = FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES
ERROR_REPORT_INTERVAL = 30
# Encode only a fixed stage and a bounded Win32 error code in the child exit
# status. No pipe names, tokens, paths or command lines cross diagnostics.
HELPER_ERRORS = {1: "arguments", 2: "open", 3: "server_identity", 4: "sample", 5: "write"}
HELPER_ERROR_BASE = 0x100000


def pipe_sddl(sid):
    return f"D:P(A;;GA;;;SY)(A;;0x{PIPE_USER_ACCESS:08x};;;{sid})"


def helper_error(stage, error=None):
    code = getattr(error, "winerror", None)
    if type(code) is not int or not 0 <= code <= 0xffff:
        code = 0
    return HELPER_ERROR_BASE | (stage << 16) | code


def describe_exit(code):
    if type(code) is int and code & 0xfff00000 == HELPER_ERROR_BASE:
        stage = HELPER_ERRORS.get((code >> 16) & 0xf)
        if stage:
            return stage, code & 0xffff
    return "exit", code



def session_state(session):
    """WTSInfoEx (Windows 10/11 x64): distinguish confirmed lock from failure."""
    from ctypes import wintypes as w

    class Level1(ctypes.Structure):
        _fields_ = [("session", w.ULONG), ("state", ctypes.c_int),
                    ("flags", w.LONG), ("station", w.WCHAR * 33),
                    ("user", w.WCHAR * 21), ("domain", w.WCHAR * 18),
                    ("times", ctypes.c_longlong * 5), ("counters", w.DWORD * 6)]

    class Info(ctypes.Structure):
        _fields_ = [("level", w.DWORD), ("data", Level1)]

    api = ctypes.WinDLL("wtsapi32", use_last_error=True)
    query = api.WTSQuerySessionInformationW
    query.argtypes = [w.HANDLE, w.DWORD, ctypes.c_int,
                      ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD)]
    query.restype = w.BOOL
    free = api.WTSFreeMemory
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    ptr, size = ctypes.c_void_p(), w.DWORD()
    # WTSSessionInfoEx is 25; WTSActive is 0.
    if not query(None, session, 25, ctypes.byref(ptr), ctypes.byref(size)):
        return "unknown"
    try:
        if size.value < ctypes.sizeof(Info):
            return "unknown"
        value = ctypes.cast(ptr, ctypes.POINTER(Info)).contents
        if value.level != 1 or value.data.session != session or value.data.state != 0:
            return "unknown"
        return {0: "locked", 1: "unlocked"}.get(value.data.flags, "unknown")
    finally:
        free(ptr)


def selected_session():
    import win32ts
    ids = sorted(s["SessionId"] for s in win32ts.WTSEnumerateSessions()
                 if s["State"] == win32ts.WTSActive and s["SessionId"] > 0)
    if not ids:
        return None, "idle"
    console = win32ts.WTSGetActiveConsoleSessionId()
    if console in ids:
        session = console
    elif len(ids) == 1:
        session = ids[0]
    else:
        return None, "unknown"
    return session, session_state(session)


def helper_main(pipe_name, parent_pid):
    """Child runs unelevated in the selected user's interactive session."""
    import pywintypes
    import win32file
    import win32pipe

    if not re.fullmatch(re.escape(PIPE_PREFIX) + r"[0-9a-f]{32}", pipe_name):
        return helper_error(1)
    try:
        expected_parent = int(parent_pid)
        if expected_parent <= 0:
            return helper_error(1)
    except (ValueError, TypeError):
        return helper_error(1)
    handle = None
    stage = 2
    try:
        handle = win32file.CreateFile(pipe_name, 0x40000000, 0, None, 3, 0x00110000, None)
        stage = 3
        if win32pipe.GetNamedPipeServerProcessId(handle) != expected_parent:
            return helper_error(stage)
        while True:
            stage = 4
            payload = json.dumps(sample_window(), separators=(",", ":")).encode("ascii")
            stage = 5
            win32file.WriteFile(handle, payload)
            time.sleep(SAMPLE_PERIOD)
    except (pywintypes.error, OSError, ValueError) as err:
        return helper_error(stage, err)
    finally:
        if handle is not None:
            handle.Close()


class FocusProbe:
    def __init__(self):
        self.pipe = None
        self.process = None
        self.pid = None
        self.session = None
        self.started = 0
        self.retry_after = 0
        self.last_error_report = float('-inf')

    def _report_error(self, stage, code):
        now = time.monotonic()
        if now - self.last_error_report >= ERROR_REPORT_INTERVAL:
            LOG.warning("Foreground helper unavailable: stage=%s error_code=%s", stage, code)
            self.last_error_report = now

    def _report_child_exit(self, wait_ms=0):
        if self.process is None:
            return False
        import win32event
        import win32process
        try:
            if win32event.WaitForSingleObject(self.process, wait_ms) != win32event.WAIT_OBJECT_0:
                return False
            stage, code = describe_exit(win32process.GetExitCodeProcess(self.process))
            self._report_error(stage, code)
            return True
        except Exception as err:
            self._report_error("exit_query", getattr(err, "winerror", None) or 0)
            return False

    def close(self):
        if self.pipe is not None:
            self.pipe.Close()
            self.pipe = None
        if self.process is not None:
            import win32event
            import win32process
            try:
                if win32event.WaitForSingleObject(self.process, 0) == win32event.WAIT_TIMEOUT:
                    win32process.TerminateProcess(self.process, 0)
            except Exception:
                LOG.warning("Unable to stop foreground helper")
            finally:
                self.process.Close()
                self.process = None
        self.pid = self.session = None

    def _start(self, session):
        import pywintypes
        import win32con
        import win32pipe
        import win32process
        import win32profile
        import win32security
        import win32ts

        token = win32ts.WTSQueryUserToken(session)
        try:
            sid = win32security.ConvertSidToStringSid(
                win32security.GetTokenInformation(token, win32security.TokenUser)[0])
            sa = pywintypes.SECURITY_ATTRIBUTES()
            sa.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                pipe_sddl(sid), win32security.SDDL_REVISION_1)
            sa.bInheritHandle = False
            name = PIPE_PREFIX + secrets.token_hex(16)
            self.pipe = win32pipe.CreateNamedPipe(
                name, win32pipe.PIPE_ACCESS_INBOUND | 0x00080000,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE |
                win32pipe.PIPE_NOWAIT | 0x8, 1, 0, 4096, 0, sa)
            executable = str(Path(sys.executable).resolve())
            args = [executable]
            if not getattr(sys, "frozen", False):
                args.append(str(Path(__file__).resolve().parent.parent / "service_entry.py"))
            args.extend(["--focus-helper", name, str(os.getpid())])
            info = win32process.STARTUPINFO()
            info.lpDesktop = r"winsta0\default"
            env = win32profile.CreateEnvironmentBlock(token, False)
            self.process, thread, self.pid, _ = win32process.CreateProcessAsUser(
                token, executable, subprocess.list2cmdline(args), None, None, False,
                win32con.CREATE_NO_WINDOW | win32con.CREATE_UNICODE_ENVIRONMENT,
                env, str(Path(executable).parent), info)
            thread.Close()
            self.session = session
            self.started = time.monotonic()
        finally:
            token.Close()

    def _receive(self):
        import pywintypes
        import win32pipe
        import win32file
        try:
            win32pipe.ConnectNamedPipe(self.pipe, None)
        except pywintypes.error as err:
            if err.winerror == 536:  # ERROR_PIPE_LISTENING
                return None
            if err.winerror != 535:  # ERROR_PIPE_CONNECTED
                raise
        if win32pipe.GetNamedPipeClientProcessId(self.pipe) != self.pid:
            raise ValueError("Unexpected foreground helper PID")
        latest = None
        # Bound accumulated data and only accept a newly read sample.
        for _ in range(16):
            _, available, _ = win32pipe.PeekNamedPipe(self.pipe, 0)
            if not available:
                break
            rc, raw = win32file.ReadFile(self.pipe, 1024)
            if rc != 0 or len(raw) > 1024:
                raise ValueError("Invalid foreground message")
            latest = json.loads(raw)
        return latest

    def read(self, rules):
        self.candidate = None  # never carry identity over a failed or stale probe
        self.foreground_state = "unknown"
        try:
            session, status = selected_session()
            if status != "unlocked":
                self.foreground_state = "idle" if status in ("idle", "locked") else "unknown"
                self.close()
                return dict(IDLE if status in ("idle", "locked") else UNKNOWN)
            if session != self.session:
                self.close()
            if self._report_child_exit():
                self.close()
                self.retry_after = time.monotonic() + 2
            now = time.monotonic()
            if self.process is None:
                if now >= self.retry_after:
                    self.retry_after = now + 2
                    self._start(session)
                return dict(UNKNOWN)
            sample = self._receive()
            now = time.monotonic()
            if sample is None:
                # Do not reuse a previous ON reading; restart a stalled helper.
                if now - self.started > 5:
                    self._report_error("sample_timeout", 0)
                    self.close()
                    self.retry_after = now + 2
                return dict(UNKNOWN)
            result = classify(sample, session, now, rules, session_lookup=process_session_id)
            # A lock or session switch while reading invalidates the sample.
            current, state = selected_session()
            if current != session or state != "unlocked":
                self.foreground_state = "idle" if state in ("idle", "locked") else "unknown"
                self.close()
                return dict(IDLE if state in ("idle", "locked") else UNKNOWN)
            if isinstance(sample, dict) and isinstance(sample.get("time"), (int, float)) and now - sample["time"] <= MAX_SAMPLE_AGE:
                self.started = now
                if result != UNKNOWN:
                    self.candidate = candidate_from_sample(
                        sample, session, now, session_lookup=process_session_id)
                    if self.candidate is not None:
                        self.foreground_state = "foreground"
                    elif sample.get("status") == "idle":
                        self.foreground_state = "idle"
            return result
        except Exception as err:
            # A failed open/write can close the pipe just before the child
            # exits. Prefer its precise stage and code over a generic read error.
            if not self._report_child_exit(wait_ms=100):
                self._report_error("probe", getattr(err, "winerror", None) or 0)
            self.close()
            self.retry_after = time.monotonic() + 2
            return dict(UNKNOWN)
