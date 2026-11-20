"""Foreground telemetry: one game, confirmed idle, or unknown.

The interactive helper only reports window process identity. The service owns
rules, validates the identity, and classifies the result. No local policy.
"""
import math
import time
import psutil

from .core import match_game

MAX_SAMPLE_AGE = 1.5
UNKNOWN = {"gaming_active": "UNKNOWN", "active_game": "unknown"}
IDLE = {"gaming_active": "OFF", "active_game": "idle"}


def _valid_sample(sample, session, now):
    if not isinstance(sample, dict) or type(session) is not int or session <= 0:
        return False
    tick = sample.get("time")
    return (type(tick) in (int, float) and math.isfinite(tick)
            and 0 <= now - tick <= MAX_SAMPLE_AGE)


def _valid_process_identity(pid, created):
    return (type(pid) is int and pid > 0
            and type(created) in (int, float) and math.isfinite(created))


def _match_process(proc, rules):
    name = proc.name()
    candidates = [r for r in rules if r["process"].casefold() == name.casefold()]
    info = {"name": name}
    if any("path_contains" in r for r in candidates):
        info["exe"] = proc.exe()
    if any("command_line_arg" in r for r in candidates):
        info["cmdline"] = proc.cmdline()
    return match_game(info, candidates)


def classify(sample, session, now, rules, process_factory=psutil.Process, session_lookup=None):
    """Untrusted samples must be recent and belong to the selected session."""
    if not _valid_sample(sample, session, now):
        return dict(UNKNOWN)
    if sample.get("status") == "idle":
        return dict(IDLE)
    if sample.get("status") != "window":
        return dict(UNKNOWN)
    pid, created = sample.get("pid"), sample.get("created")
    if not _valid_process_identity(pid, created):
        return dict(UNKNOWN)
    try:
        proc = process_factory(pid)
        if proc.create_time() != created or not proc.is_running():
            return dict(UNKNOWN)
        if session_lookup is None or session_lookup(pid) != session:
            return dict(UNKNOWN)
        game = _match_process(proc, rules)
        if not proc.is_running() or proc.create_time() != created:
            return dict(UNKNOWN)
    except (psutil.Error, OSError, ValueError):
        return dict(UNKNOWN)
    return {"gaming_active": "ON", "active_game": game} if game else dict(IDLE)



def candidate_from_sample(sample, session, now, process_factory=psutil.Process,
                          session_lookup=None):
    """Return only a verified focused executable and private process identity.

    PID, creation timestamp and session never leave the Windows agent. A
    candidate does not authorize a new rule, a termination or an update.
    Generic runtimes need a separate discriminator before enrollment.
    """
    import re

    if (not _valid_sample(sample, session, now)
            or sample.get("status") != "window"
            or not _valid_process_identity(sample.get("pid"), sample.get("created"))
            or session_lookup is None):
        return None
    pid, created = sample["pid"], sample["created"]
    try:
        proc = process_factory(pid)
        if (proc.create_time() != created or not proc.is_running()
                or session_lookup(pid) != session):
            return None
        name = proc.name()
        if (not isinstance(name, str) or len(name) > 128
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.'()+-]*\\.exe", name, re.IGNORECASE)):
            return None
        if not proc.is_running() or proc.create_time() != created:
            return None
        return (name, pid, created, session)
    except (psutil.Error, OSError, ValueError, TypeError):
        return None

def sample_window():
    """Run only on the interactive desktop. Verify focus after reading PID."""
    import win32gui
    import win32process
    import pywintypes

    start = time.monotonic()
    result = {"time": start, "status": "unknown"}
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return result
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return result
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        idle = (win32gui.IsIconic(hwnd) or not win32gui.IsWindowVisible(hwnd)
                or right <= left or bottom <= top)
        proc = psutil.Process(pid)
        created = proc.create_time()
        if (win32gui.GetForegroundWindow() != hwnd
                or win32process.GetWindowThreadProcessId(hwnd)[1] != pid
                or not proc.is_running()):
            return result
        return {"time": start, "status": "idle"} if idle else {
            "time": start, "status": "window", "pid": pid, "created": created}
    except (psutil.Error, OSError, pywintypes.error):
        return result
