"""Service-to-interactive-user popup bridge, isolated from foreground probe.

Only an accepted HA popup v1 packet may create/update the helper. The helper
runs as the active unlocked user, never on SYSTEM Session 0; no OS commands
may cross this pipe. No gaming policy is executed by this module.
"""
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from .focus_session import selected_session
from .popup_helper import PIPE_PREFIX, pipe_sddl
from .popup_protocol import valid_event, validate_popup
from .windows import process_session_id

LOG = logging.getLogger(__name__)
MAX_PIPE_BYTES = 4096
PIPE_RETRY_SECONDS = 2


class PopupSession:
    def __init__(self):
        self.pipe = None
        self.process = None
        self.pid = None
        self.session = None
        self.started = 0
        self.retry_after = 0
        self.pending = None
        self.packet = None
        self.deadline = 0
        self.seen_events = []

    def close(self):
        """Service shutdown, lock, disconnect, stale view: destroy child."""
        if self.pipe is not None:
            try:
                self.pipe.Close()
            finally:
                self.pipe = None
        if self.process is not None:
            import win32event
            import win32process
            try:
                if win32event.WaitForSingleObject(self.process, 0) == win32event.WAIT_TIMEOUT:
                    win32process.TerminateProcess(self.process, 0)
            except (OSError, ValueError):
                LOG.warning("Unable to terminate popup helper cleanly")
            finally:
                self.process.Close()
                self.process = None
        self.pid = self.session = None
        self.pending = self.packet = None
        self.deadline = 0
        self.seen_events = []

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
                win32security.GetTokenInformation(
                    token, win32security.TokenUser)[0])
            attrs = pywintypes.SECURITY_ATTRIBUTES()
            attrs.SECURITY_DESCRIPTOR = (
                win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                    pipe_sddl(sid), win32security.SDDL_REVISION_1))
            attrs.bInheritHandle = False
            name = PIPE_PREFIX + secrets.token_hex(16)
            self.pipe = win32pipe.CreateNamedPipe(
                name, win32pipe.PIPE_ACCESS_DUPLEX | 0x00080000,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE |
                win32pipe.PIPE_NOWAIT | 0x8,
                1, MAX_PIPE_BYTES, MAX_PIPE_BYTES, 0, attrs)
            executable = str(Path(sys.executable).resolve())
            args = [executable]
            if not getattr(sys, "frozen", False):
                args.append(str(Path(__file__).resolve().parent.parent / "service_entry.py"))
            # The only child mode and path are hardcoded locally, not supplied
            # in MQTT text or view descriptions.
            args.extend(["--popup-helper", name, str(os.getpid()), self._device_id])
            info = win32process.STARTUPINFO()
            info.lpDesktop = r"winsta0\default"
            env = win32profile.CreateEnvironmentBlock(token, False)
            self.process, thread, self.pid, _ = win32process.CreateProcessAsUser(
                token, executable, subprocess.list2cmdline(args),
                None, None, False,
                win32con.CREATE_NO_WINDOW | win32con.CREATE_UNICODE_ENVIRONMENT,
                env, str(Path(executable).parent), info)
            thread.Close()
            self.session = session
            self.started = time.monotonic()
        finally:
            token.Close()

    def handle(self, packet, device_id):
        """Enqueue a *new validated* HA instruction; no automatic redisplay."""
        try:
            validate_popup(packet, device_id, retained=False)
        except (ValueError, TypeError):
            return False
        self._device_id = device_id
        if packet["operation"] == "refresh":
            return self._refresh(packet)
        if packet["operation"] == "hide":
            if self.process is not None:
                self.pending = packet
            else:
                self.pending = None
            self.packet = None
            self.deadline = 0
        else:
            self.packet = packet
            self.deadline = time.monotonic() + packet["display_stale_after_seconds"]
            self.pending = packet
        return True

    def _refresh(self, packet):
        """Only an already relayed v2 show can receive a refresh."""
        if (self.process is None or self.pipe is None or self.packet is None
                or self.packet["version"] != 2 or self.pending is not None
                or time.monotonic() >= self.deadline
                or packet["popup_id"] != self.packet["popup_id"]
                or packet["producer_epoch"] != self.packet["producer_epoch"]):
            return False
        self.pending = packet
        self.deadline = time.monotonic() + packet["display_stale_after_seconds"]
        return True

    def _connect(self):
        import pywintypes
        import win32pipe

        if self.pipe is None:
            return False
        try:
            win32pipe.ConnectNamedPipe(self.pipe, None)
        except pywintypes.error as exc:
            if exc.winerror == 536:  # waiting for helper
                return False
            if exc.winerror != 535:  # already connected
                raise
        if win32pipe.GetNamedPipeClientProcessId(self.pipe) != self.pid:
            raise ValueError("Unexpected popup pipe client PID")
        if process_session_id(self.pid) != self.session:
            raise ValueError("Unexpected popup helper session")
        return True

    def _flush(self):
        import win32file

        if self.pending is None or self.pipe is None:
            return
        # Service must recheck wall TTL if helper connection was slow.
        packet = self.pending
        try:
            validate_popup(packet, self._device_id, retained=False)
        except (ValueError, TypeError):
            self.pending = None
            return
        raw = json.dumps(packet, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_PIPE_BYTES:
            raise ValueError("Popup IPC packet exceeds pipe capacity")
        status, _ = win32file.WriteFile(self.pipe, raw)
        if status != 0:
            raise ValueError("Popup pipe write failed")
        self.pending = None

    def _events(self, bridge):
        import win32file
        import win32pipe

        for _ in range(8):
            _, available, _ = win32pipe.PeekNamedPipe(self.pipe, 0)
            if not available:
                return
            if available > 1024:
                raise ValueError("Oversized popup helper response")
            status, raw = win32file.ReadFile(self.pipe, 1024)
            if status != 0 or len(raw) > 1024:
                raise ValueError("Invalid popup helper response")
            try:
                value = json.loads(raw)
            except (ValueError, TypeError, UnicodeError):
                continue
            if not valid_event(value, self.packet, bridge.id):
                continue
            if value["event_id"] in self.seen_events:
                continue
            self.seen_events.append(value["event_id"])
            self.seen_events = self.seen_events[-64:]
            bridge.publish_popup_event(value)
            if value["kind"] == "closed" and self.packet["version"] == 2:
                self.packet = self.pending = None
                self.deadline = 0

    def pump(self, bridge):
        """Poll from service main loop; hide promptly if stale/locked/offline."""
        if not bridge.connected:
            self.close()
            return
        session, status = selected_session()
        if status != "unlocked" or session is None:
            if self.process is not None:
                self.close()
            self.pending = self.packet = None
            return
        if self.session is not None and session != self.session:
            self.close()
            return
        if self.packet is not None and time.monotonic() >= self.deadline:
            self.close()
            return
        if self.pending is None and self.process is None:
            return
        try:
            import win32event
            if self.process is not None and win32event.WaitForSingleObject(
                    self.process, 0) == win32event.WAIT_OBJECT_0:
                self.close()
                self.retry_after = time.monotonic() + PIPE_RETRY_SECONDS
                return
            if self.process is None:
                if self.packet is None or time.monotonic() < self.retry_after:
                    return
                self._start(session)
            if not self._connect():
                if time.monotonic() - self.started > 5:
                    raise ValueError("Popup helper connection timeout")
                return
            self._events(bridge)
            self._flush()
        except (OSError, ValueError):
            LOG.warning("Popup helper unavailable; resetting session", exc_info=True)
            self.close()
            self.retry_after = time.monotonic() + PIPE_RETRY_SECONDS
