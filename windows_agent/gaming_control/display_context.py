"""Read-only Windows display timeout and interactive-session idle primitives.

This is NOT an OFF detector. Power policy is context, not evidence that the
monitor actually powered down. No changes to Windows power settings occur.
GetLastInputInfo MUST run in the interactive user session, not Session 0.
"""
import ctypes
from ctypes import wintypes
import uuid

VIDEO_SUBGROUP = "7516b95f-f776-4464-8c53-06167f40cc99"
VIDEO_IDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"
MAX_INPUT_IDLE_MS = 24 * 60 * 60 * 1000


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
    ]


class SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE), ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE), ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _guid(identifier):
    return GUID.from_buffer_copy(uuid.UUID(identifier).bytes_le)


def _native_display_policy():
    """Use PowerRead*ValueIndex rather than parsing localized powercfg output."""
    power = ctypes.WinDLL("powrprof", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_scheme = power.PowerGetActiveScheme
    get_scheme.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(GUID))]
    get_scheme.restype = wintypes.DWORD
    ac = power.PowerReadACValueIndex
    dc = power.PowerReadDCValueIndex
    for read in (ac, dc):
        read.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID),
                         ctypes.POINTER(GUID), ctypes.POINTER(GUID),
                         ctypes.POINTER(wintypes.DWORD)]
        read.restype = wintypes.DWORD
    free = kernel.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    scheme = ctypes.POINTER(GUID)()
    if get_scheme(None, ctypes.byref(scheme)) != 0 or not scheme:
        raise OSError("Unable to identify Windows active power plan")
    try:
        group, setting = _guid(VIDEO_SUBGROUP), _guid(VIDEO_IDLE)
        ac_index, dc_index = wintypes.DWORD(), wintypes.DWORD()
        if ac(None, scheme, ctypes.byref(group),
              ctypes.byref(setting), ctypes.byref(ac_index)) != 0:
            raise OSError("Windows AC video timeout unavailable")
        if dc(None, scheme, ctypes.byref(group),
              ctypes.byref(setting), ctypes.byref(dc_index)) != 0:
            raise OSError("Windows DC video timeout unavailable")
    finally:
        free(scheme)

    status = SystemPowerStatus()
    get_power = kernel.GetSystemPowerStatus
    get_power.argtypes = [ctypes.POINTER(SystemPowerStatus)]
    get_power.restype = wintypes.BOOL
    source = "unknown"
    if get_power(ctypes.byref(status)):
        source = {0: "battery", 1: "ac"}.get(status.ACLineStatus, "unknown")
    return ac_index.value, dc_index.value, source


def read_display_policy(reader=None):
    """Return AC/DC timeout seconds or unknown; 0 means Never, not screen OFF."""
    try:
        ac, dc, source = (reader or _native_display_policy)()
        if (type(ac) is not int or not 0 <= ac <= 0xffffffff
                or type(dc) is not int or not 0 <= dc <= 0xffffffff
                or source not in ("ac", "battery", "unknown")):
            raise ValueError("Invalid Windows display policy result")
        return {"ac_timeout_seconds": ac, "dc_timeout_seconds": dc,
                "power_source": source}
    except (OSError, AttributeError, ValueError, TypeError):
        return {"ac_timeout_seconds": None, "dc_timeout_seconds": None,
                "power_source": "unknown"}


def elapsed_input_ms(now_ticks, last_input_tick):
    """Handle the Win32 32-bit input tick rollover without inventing old idle."""
    if (type(now_ticks) is not int or not 0 <= now_ticks <= 0xffffffffffffffff
            or type(last_input_tick) is not int
            or not 0 <= last_input_tick <= 0xffffffff):
        return None
    elapsed = ((now_ticks & 0xffffffff) - last_input_tick) & 0xffffffff
    return elapsed if elapsed <= MAX_INPUT_IDLE_MS else None


def read_interactive_input_idle_ms():
    """Run ONLY in the signed-in user's session; never query from SYSTEM."""
    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        get_last = user.GetLastInputInfo
        get_last.argtypes = [ctypes.POINTER(LastInputInfo)]
        get_last.restype = wintypes.BOOL
        ticks = kernel.GetTickCount64
        ticks.argtypes = []
        ticks.restype = ctypes.c_ulonglong
        value = LastInputInfo()
        value.cbSize = ctypes.sizeof(LastInputInfo)
        if not get_last(ctypes.byref(value)):
            return None
        return elapsed_input_ms(int(ticks()), int(value.dwTime))
    except (OSError, AttributeError, ValueError):
        return None
