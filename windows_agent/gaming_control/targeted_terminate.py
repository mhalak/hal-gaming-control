"""Strict v1 targeted termination: no PID, path or executable from MQTT.

The opaque capability lives only on the Windows agent, is single-use and bound
to a recent verified foreground sample. The interactive helper must produce a
NEW sample after the parent's command before the target is terminated.
"""
import json
import math
import ntpath
import os
import re

import psutil

from .foreground import _java_identity

TARGET_TTL = 4.0
_TOKEN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_EXE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.'()+-]*\.exe\Z", re.IGNORECASE | re.ASCII)
_PROTECTED = frozenset((
    "explorer.exe", "winlogon.exe", "csrss.exe", "smss.exe", "services.exe",
    "lsass.exe", "svchost.exe", "dwm.exe", "taskmgr.exe", "sihost.exe",
    "conhost.exe", "systemsettings.exe", "searchhost.exe", "msmpeng.exe",
    "securityhealthservice.exe", "smarthousegamingcontrol.exe",
    "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe",
))


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate targeted command field")
        obj[key] = value
    return obj


def parse_target_request(payload, device_id, epoch):
    """Decode a device/connection-scoped token; never accept a requested PID."""
    if not isinstance(payload, (bytes, str)) or not 0 < len(payload) <= 512:
        raise ValueError("Invalid targeted command size")
    try:
        data = json.loads(payload, object_pairs_hook=_unique)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid targeted command JSON") from exc
    if (not isinstance(data, dict)
            or set(data) != {"version", "device_id", "epoch", "token", "request_id"}
            or type(data["version"]) is not int or data["version"] != 1
            or data["device_id"] != device_id or data["epoch"] != epoch
            or not isinstance(data["token"], str) or not _TOKEN.fullmatch(data["token"])
            or not isinstance(data["request_id"], str) or not _TOKEN.fullmatch(data["request_id"])):
        raise ValueError("Invalid targeted command fields")
    return data


def _valid_candidate(candidate):
    return (isinstance(candidate, tuple) and len(candidate) == 5
            and isinstance(candidate[0], str) and _EXE.fullmatch(candidate[0]) is not None
            and type(candidate[1]) is int and candidate[1] > 0
            and type(candidate[2]) in (int, float) and math.isfinite(candidate[2])
            and type(candidate[3]) is int and candidate[3] > 0
            and (candidate[4] is None or
                 isinstance(candidate[4], dict)))


def _allowed_exe(exe, root):
    """Reject system-directory and relative/UNC processes, even with valid PID."""
    if not isinstance(exe, str) or re.match(r"^[A-Za-z]:[\\/]", exe) is None:
        return False
    system = ntpath.normcase(ntpath.normpath(root)).rstrip("\\")
    target = ntpath.normcase(ntpath.normpath(exe))
    return not (target == system or target.startswith(system + "\\"))



def _fresh_clock(offered_sample, current_sample, offered_at, now):
    return (type(offered_at) in (int, float) and math.isfinite(offered_at)
            and type(now) in (int, float) and math.isfinite(now)
            and 0 <= now - offered_at < TARGET_TTL
            and type(offered_sample) in (int, float)
            and type(current_sample) in (int, float)
            and math.isfinite(offered_sample) and math.isfinite(current_sample)
            and offered_sample < current_sample <= now)


def _allowed_target(candidate, session, own_pid):
    name, pid, _, user_session, signature = candidate
    return (session == (user_session, "unlocked")
            and pid != (os.getpid() if own_pid is None else own_pid)
            and name.casefold() not in _PROTECTED
            and not (name.casefold() in ("java.exe", "javaw.exe")
                     and signature is None))


def _same_process(proc, candidate, session_lookup, system_root):
    name, pid, created, user_session, signature = candidate
    if (proc.pid != pid or proc.create_time() != created
            or not proc.is_running() or proc.name().casefold() != name.casefold()
            or session_lookup(pid) != user_session
            or not _allowed_exe(proc.exe(), system_root)):
        return False
    return (name.casefold() not in ("java.exe", "javaw.exe")
            or _java_identity(proc.cmdline()) == signature)


def terminate_verified(expected, observed, *, offered_sample, current_sample,
                       offered_at, now, session, process_factory=psutil.Process,
                       session_lookup, own_pid=None, system_root=None):
    """Kill one reverified user-owned foreground process, never a supplied MQTT PID."""
    if (not _valid_candidate(expected) or expected != observed
            or not _fresh_clock(offered_sample, current_sample, offered_at, now)
            or not _allowed_target(expected, session, own_pid)):
        return False
    _, pid, created, _, _ = expected
    try:
        proc = process_factory(pid)
        root = system_root or os.environ.get("SystemRoot", "C:/Windows")
        if not _same_process(proc, expected, session_lookup, root):
            return False
        if not proc.is_running() or proc.create_time() != created:
            return False
        proc.terminate()
        return True
    except (psutil.Error, OSError, TypeError, ValueError):
        return False
