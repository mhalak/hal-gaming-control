"""Windows-only primitives. Imports are lazy so unit tests run on Linux."""
import ctypes
import logging
import os
from pathlib import Path
import subprocess
import sys

LOG = logging.getLogger(__name__)


def system_uptime():
    """Elapsed system uptime, not agent/process uptime."""
    get_ticks = ctypes.WinDLL('kernel32').GetTickCount64
    get_ticks.restype = ctypes.c_ulonglong
    get_ticks.argtypes = []
    return get_ticks() // 1000


def process_session_id(pid):
    """Best-effort Windows session diagnostics, never a detection criterion."""
    try:
        from ctypes import wintypes
        result = wintypes.DWORD()
        query = ctypes.WinDLL('kernel32', use_last_error=True).ProcessIdToSessionId
        query.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        return result.value if query(pid, ctypes.byref(result)) else None
    except (AttributeError, OSError, ValueError):
        return None


def lock_this_session():
    """Run only inside the interactive user session."""
    lock = ctypes.WinDLL('user32', use_last_error=True).LockWorkStation
    lock.argtypes = []
    lock.restype = ctypes.c_int
    return 0 if lock() else 1


def select_session(sessions, console_id, active_state):
    ids = sorted(s['SessionId'] for s in sessions
                 if s['State'] == active_state and s['SessionId'] > 0)
    if console_id in ids:
        return console_id
    # Avoid locking an arbitrary user when several remote sessions are active.
    return ids[0] if len(ids) == 1 else None


def lock_active_session():
    """Launch a fixed lock helper in the active user's session, as that user."""
    import win32con
    import win32event
    import win32process
    import win32profile
    import win32ts

    session = select_session(win32ts.WTSEnumerateSessions(),
                             win32ts.WTSGetActiveConsoleSessionId(), win32ts.WTSActive)
    if session is None:
        LOG.warning('Lock ignored: no unambiguous active interactive session')
        return
    executable = str(Path(sys.executable).resolve())
    args = [executable]
    if not getattr(sys, 'frozen', False):
        args.append(str(Path(__file__).resolve().parent.parent / 'service_entry.py'))
    args.append('--lock-session')
    si = win32process.STARTUPINFO()
    si.lpDesktop = 'winsta0\\default'
    token = win32ts.WTSQueryUserToken(session)
    try:
        env = win32profile.CreateEnvironmentBlock(token, False)
        process, thread, _, _ = win32process.CreateProcessAsUser(
            token, executable, subprocess.list2cmdline(args), None, None, False,
            win32con.CREATE_NO_WINDOW | win32con.CREATE_UNICODE_ENVIRONMENT,
            env, str(Path(executable).parent), si)
        try:
            result = win32event.WaitForSingleObject(process, 5000)
            if result != win32event.WAIT_OBJECT_0:
                LOG.warning('Lock helper did not complete within five seconds')
            elif win32process.GetExitCodeProcess(process) != 0:
                LOG.warning('LockWorkStation did not accept request (possibly already locked)')
            else:
                LOG.info('Lock request initiated for session %s', session)
        finally:
            thread.Close()
            process.Close()
    finally:
        token.Close()
