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
    if not isinstance(exe, str) or not ntpath.isabs(exe) or exe.startswith("\\\\"):
        return False
    system = ntpath.normcase(ntpath.normpath(root)).rstrip("\\")
    target = ntpath.normcase(ntpath.normpath(exe))
    return not (target == system or target.startswith(system + "\\"))


def terminate_verified(expected, observed, *, offered_sample, current_sample,
                       offered_at, now, session, process_factory=psutil.Process,
                       session_lookup, own_pid=None, system_root=None):
    """Terminate exactly one independently verified *currently focused* process.

    Both identities come from the Windows user's trusted foreground helper,
    not MQTT. A fresh helper sample must have been read after the offer.
    """
    if not _valid_candidate(expected) or expected != observed:
        return False
    if (type(offered_at) not in (int, float) or not math.isfinite(offered_at)
            or type(now) not in (int, float) or not math.isfinite(now)
            or not 0 <= now - offered_at < TARGET_TTL
            or type(offered_sample) not in (int, float)
            or type(current_sample) not in (int, float)
            or not math.isfinite(offered_sample) or not math.isfinite(current_sample)
            or not offered_sample < current_sample <= now):
        return False
    name, pid, created, user_session, signature = expected
    if (session != (user_session, "unlocked")
            or pid == (os.getpid() if own_pid is None else own_pid)
            or name.casefold() in _PROTECTED
            or (name.casefold() in ("java.exe", "javaw.exe") and signature is None)):
        return False
    try:
        proc = process_factory(pid)
        if (proc.pid != pid or proc.create_time() != created
                or not proc.is_running()
                or proc.name().casefold() != name.casefold()
                or session_lookup(pid) != user_session
                or not _allowed_exe(proc.exe(), system_root or os.environ.get("SystemRoot", "C:/Windows"))):
            return False
        if (name.casefold() in ("java.exe", "javaw.exe")
                and _java_identity(proc.cmdline()) != signature):
            return False
        if not proc.is_running() or proc.create_time() != created:
            return False
        proc.terminate()
        return True
    except (psutil.Error, OSError, TypeError, ValueError):
        return False
