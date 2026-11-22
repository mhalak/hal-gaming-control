"""Session-local Windows console display power notifications (telemetry only).

The observer must run on the *interactive user's* thread. A hidden top-level
HWND and a nonblocking message pump receive GUID_CONSOLE_DISPLAY_STATE
notifications; never use a SYSTEM service window for console power events.

These are logical Windows *console* display states, NOT proof that every
physical monitor is off, nor proof of user inactivity. No policy/bonus here.
"""
import ctypes
import math
import secrets
import time
import uuid

from .display_context import GUID, _guid

CONSOLE_DISPLAY_GUID = "6fe69556-704a-47a0-8f24-c28d936fda47"
_GUID_BYTES = uuid.UUID(CONSOLE_DISPLAY_GUID).bytes_le
WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007
WM_DISPLAYCHANGE = 0x007E
# The event is valid while this exact helper/window stays alive and pumps
# messages. Expire even a live helper after a day without a further event.
MAX_EVENT_AGE_MS = 24 * 60 * 60 * 1000
_STATE = {0: "off", 1: "on", 2: "dim"}


def decode_console_display_event(raw):
    """Parse exact POWERBROADCAST_SETTING header+DWORD, little-endian.

    Unrelated GUID => None, malformed/unknown value => 'unknown'.
    Windows owns the lParam pointer; parse bounded bytes, not arbitrary input.
    """
    if not isinstance(raw, bytes) or len(raw) != 24:
        return "unknown"
    if raw[:16] != _GUID_BYTES:
        return None
    if int.from_bytes(raw[16:20], "little") != 4:
        return "unknown"
    return _STATE.get(int.from_bytes(raw[20:24], "little"), "unknown")


class DisplayStateTracker:
    """Pure state machine, reset on helper launch, suspension or ambiguity."""

    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.invalidate()

    def invalidate(self):
        self.state = "unknown"
        self.changed = None

    def receive(self, raw):
        state = decode_console_display_event(raw)
        if state is None:
            return False
        if state == "unknown":
            self.invalidate()
            return True
        self.state = state
        self.changed = self.clock()
        return True

    def snapshot(self):
        if self.changed is None or self.state == "unknown":
            return {"display_state": "unknown", "display_event_age_ms": None}
        elapsed = (self.clock() - self.changed) * 1000
        if not math.isfinite(elapsed) or not 0 <= elapsed <= MAX_EVENT_AGE_MS:
            self.invalidate()
            return {"display_state": "unknown", "display_event_age_ms": None}
        return {"display_state": self.state, "display_event_age_ms": int(elapsed)}


class DisplayObserver:
    """Registers a hidden window *inside* the existing user-session helper."""

    def __init__(self, *, tracker=None):
        self.tracker = tracker or DisplayStateTracker()
        self.window = None
        self.notification = None
        self.class_name = None
        self.instance = None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DISPLAYCHANGE:
            self.tracker.invalidate()
        elif msg == WM_POWERBROADCAST:
            if wparam in (PBT_APMSUSPEND, PBT_APMRESUMEAUTOMATIC,
                          PBT_APMRESUMESUSPEND):
                self.tracker.invalidate()
            elif wparam == PBT_POWERSETTINGCHANGE:
                if type(lparam) is not int or lparam <= 0:
                    self.tracker.invalidate()
                else:
                    # Only the OS delivers WM_POWERBROADCAST to this private
                    # window; its lParam is a valid POWERBROADCAST_SETTING*.
                    self.tracker.receive(ctypes.string_at(lparam, 24))
            return 1
        import win32gui
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def start(self):
        if self.window is not None:
            return True
        try:
            import win32api
            import win32gui
            self.instance = win32api.GetModuleHandle(None)
            self.class_name = "HALGamingConsoleDisplay-" + secrets.token_hex(8)
            klass = win32gui.WNDCLASS()
            klass.hInstance = self.instance
            klass.lpszClassName = self.class_name
            klass.lpfnWndProc = self._wndproc
            win32gui.RegisterClass(klass)
            # Hidden top-level window: no WS_VISIBLE, no focus, no UI.
            self.window = win32gui.CreateWindowEx(
                0, self.class_name, "", 0, 0, 0, 0, 0,
                0, 0, self.instance, None)
            user = ctypes.WinDLL("user32", use_last_error=True)
            register = user.RegisterPowerSettingNotification
            register.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID),
                                 ctypes.c_uint32]
            register.restype = ctypes.c_void_p
            key = _guid(CONSOLE_DISPLAY_GUID)
            self.notification = register(self.window, ctypes.byref(key), 0)
            if not self.notification:
                raise OSError("RegisterPowerSettingNotification unavailable")
            return True
        except Exception:
            self.close()
            return False  # Foreground gaming detection must keep working.

    def pump(self):
        if self.window is None or not self.notification:
            self.tracker.invalidate()
            return
        try:
            import win32gui
            if win32gui.PumpWaitingMessages():
                self.tracker.invalidate()
        except Exception:
            self.close()

    def sample(self):
        return self.tracker.snapshot() if self.notification else {
            "display_state": "unknown", "display_event_age_ms": None}

    def close(self):
        # Cleanup is always called in the user helper thread.
        try:
            if self.notification:
                user = ctypes.WinDLL("user32", use_last_error=True)
                unregister = user.UnregisterPowerSettingNotification
                unregister.argtypes = [ctypes.c_void_p]
                unregister.restype = ctypes.c_int
                unregister(self.notification)
        except Exception:
            pass
        finally:
            self.notification = None
        try:
            import win32gui
            if self.window is not None:
                win32gui.DestroyWindow(self.window)
            if self.class_name is not None:
                win32gui.UnregisterClass(self.class_name, self.instance)
        except Exception:
            pass
        finally:
            self.window = None
            self.class_name = None
            self.instance = None
            self.tracker.invalidate()
