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


def classify(sample, session, now, rules, process_factory=psutil.Process, session_lookup=None):
    """Untrusted samples must be recent and belong to the selected session."""
    if not isinstance(sample, dict) or type(session) is not int or session <= 0:
        return dict(UNKNOWN)
    tick = sample.get("time")
    if type(tick) not in (int, float) or not math.isfinite(tick) or not 0 <= now - tick <= MAX_SAMPLE_AGE:
        return dict(UNKNOWN)
    if sample.get("status") == "idle":
        return dict(IDLE)
    if sample.get("status") != "window":
        return dict(UNKNOWN)
    pid, created = sample.get("pid"), sample.get("created")
    if type(pid) is not int or pid <= 0 or type(created) not in (int, float) or not math.isfinite(created):
        return dict(UNKNOWN)
    try:
        proc = process_factory(pid)
        if proc.create_time() != created or not proc.is_running():
            return dict(UNKNOWN)
        if session_lookup is None or session_lookup(pid) != session:
            return dict(UNKNOWN)
        name = proc.name()
        candidates = [r for r in rules if r["process"].casefold() == name.casefold()]
        info = {"name": name}
        if any("path_contains" in r for r in candidates):
            info["exe"] = proc.exe()
        if any("command_line_arg" in r for r in candidates):
            info["cmdline"] = proc.cmdline()
        game = match_game(info, candidates)
        if not proc.is_running() or proc.create_time() != created:
            return dict(UNKNOWN)
    except (psutil.Error, OSError, ValueError):
        return dict(UNKNOWN)
    return {"gaming_active": "ON", "active_game": game} if game else dict(IDLE)


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
