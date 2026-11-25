"""Unelevated interactive-session fixed-form popup; no MQTT or gaming policy.

Only authenticated pipe messages from the launching SYSTEM service can update
this window. Tk runs on the helper UI thread; no SYSTEM desktop window exists.
"""
import json
import re
import secrets

from .popup_model import PopupModel, BUTTON_COLORS
from .popup_protocol import parse_popup, make_event

PIPE_PREFIX = r"\\.\pipe\HALGamingPopup-"
MAX_PIPE_MESSAGE = 4096
POLL_MS = 125

# Note: this module is importable on Linux for contract tests. Tk/pywin32
# must be imported only inside the interactive user's helper process.


def pipe_sddl(sid):
    """SYSTEM full control; selected user gets pipe read/write + attributes."""
    if not isinstance(sid, str) or re.fullmatch(r"S-1-[0-9-]{5,128}", sid) is None:
        raise ValueError("Invalid session user SID")
    return f"D:P(A;;GA;;;SY)(A;;0x0012019f;;;{sid})"


def popup_helper_main(pipe_name, parent_pid, device_id):
    """Entry point: open service-owned duplex pipe after verifying parent PID."""
    import win32file
    import win32pipe
    import tkinter as tk
    import pywintypes

    if (type(pipe_name) is not str
            or re.fullmatch(re.escape(PIPE_PREFIX) + r"[0-9a-f]{32}", pipe_name) is None
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id)):
        return 2
    try:
        pid = int(parent_pid)
        if pid <= 0:
            return 2
    except (TypeError, ValueError):
        return 2
    handle = None
    root = None
    try:
        handle = win32file.CreateFile(
            pipe_name, 0xC0000000, 0, None, 3, 0, None)
        if win32pipe.GetNamedPipeServerProcessId(handle) != pid:
            return 3
        win32pipe.SetNamedPipeHandleState(
            handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        root = tk.Tk()
        ui = _PopupWindow(root, tk, handle, device_id, win32file, win32pipe)
        root.mainloop()
        return 0
    except (OSError, ValueError, RuntimeError, pywintypes.error):
        return 4
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        if handle is not None:
            handle.Close()


class _PopupWindow:
    def __init__(self, root, tk, pipe, device_id, win32file, win32pipe):
        self.root, self.tk = root, tk
        self.pipe, self.device_id = pipe, device_id
        self.win32file, self.win32pipe = win32file, win32pipe
        self.model = PopupModel()
        self.pending = []
        self.dead = False
        self._visible_fields = (True, True)
        self._layout()
        root.after(POLL_MS, self._poll)

    def _layout(self):
        tk, root = self.tk, self.root
        root.title("HAL Gaming Control")
        root.configure(bg="#111A2C")
        root.resizable(False, False)
        root.geometry("420x300")
        root.protocol("WM_DELETE_WINDOW", self._closed)
        root.withdraw()

        header = tk.Frame(root, bg="#25334C", padx=17, pady=12)
        header.pack(fill="x")
        # Brand glyph is drawn locally: no remote images or executable themes.
        badge = tk.Canvas(header, width=29, height=29, bg="#25334C",
                          highlightthickness=0)
        badge.create_oval(1, 1, 28, 28, fill="#244C80", outline="#4974B0")
        badge.create_oval(10, 10, 19, 19, fill="#74B9FF", outline="#BADFFF")
        badge.pack(side="left")
        tk.Label(header, text="  HAL Gaming Control",
                 font=("Segoe UI", 12, "bold"), bg="#25334C",
                 fg="#EDF2FC").pack(side="left")

        frame = tk.Frame(root, bg="#111A2C", padx=23, pady=16)
        frame.pack(fill="both", expand=True)
        self.heading = tk.Label(
            frame, text="", fg="#A7B7D3", bg="#111A2C",
            font=("Segoe UI", 10, "bold"), wraplength=364)
        self.heading.pack(pady=(0, 1))
        self.clock = tk.Label(
            frame, text="00:00", fg="#F5F8FF", bg="#111A2C",
            font=("Segoe UI", 43, "bold"))
        self.clock.pack(pady=(0, 9))
        self.bar = tk.Canvas(frame, width=355, height=13,
                             bg="#3C4658", highlightthickness=0)
        self.bar.pack(fill="x")
        self.fill = self.bar.create_rectangle(
            0, 0, 0, 13, fill="#ED646B", outline="")
        self.detail = tk.Frame(frame, bg="#111A2C")
        self.detail.pack(fill="x", pady=(8, 14))
        self.reason = tk.Label(self.detail, bg="#111A2C", fg="#B4C0D3",
                               font=("Segoe UI", 9))
        self.reason.pack(side="left")
        self.percent = tk.Label(self.detail, bg="#111A2C", fg="#B4C0D3",
                                font=("Segoe UI", 9))
        self.percent.pack(side="right")
        self.actions = tk.Frame(frame, bg="#111A2C")
        self.actions.pack(fill="x")
        tk.Label(root, text="P O W E R E D   B Y   H A L   S Y S T E M S",
                 font=("Segoe UI", 8), bg="#18243A", fg="#8495AE",
                 pady=10).pack(fill="x")

    def _closed(self):
        snap = self.model.snapshot()
        self.model.hide()
        self.root.withdraw()
        if snap is not None:
            self._queue_event(snap, "closed", None)

    def _queue_event(self, snap, kind, button_id):
        event = make_event(self.device_id, snap["popup_id"],
                           secrets.token_hex(16), kind, button_id)
        if len(self.pending) < 8:
            self.pending.append(json.dumps(event, separators=(",", ":")).encode("ascii"))

    def _press(self, button_id):
        snap = self.model.snapshot()
        if snap is not None:
            self._queue_event(snap, "button", button_id)

    def _set_buttons(self, buttons):
        tk = self.tk
        for child in self.actions.winfo_children():
            child.destroy()
        for i in range(3):
            self.actions.grid_columnconfigure(i, weight=0, uniform="")
        if not buttons:
            return
        for col, item in enumerate(buttons):
            self.actions.grid_columnconfigure(col, weight=1, uniform="equal")
            tk.Button(self.actions, text=item["text"],
                      command=lambda key=item["id"]: self._press(key),
                      bg=BUTTON_COLORS[item["color"]], fg="white",
                      activebackground=BUTTON_COLORS[item["color"]],
                      activeforeground="white", borderwidth=0,
                      font=("Segoe UI", 9, "bold"), cursor="hand2",
                      wraplength=115, pady=8).grid(
                          row=0, column=col, sticky="ew",
                          padx=(0, 6 if col < len(buttons) - 1 else 0))

    def _upsert(self, packet):
        self.model.upsert(packet)
        view = packet["view"]
        self.heading.configure(text=view["heading"])
        self.reason.configure(text=view["description"])
        self._set_buttons(view["buttons"])
        self._visibility()
        # Different response layouts change only the button row, not the form.
        self._paint()
        if self.root.state() == "withdrawn":
            self.root.deiconify()  # new show; an update never raises the window

    def _visibility(self):
        snap = self.model.snapshot()
        if snap is None:
            return
        visible = (snap["time"] is not None, snap["percent"] is not None)
        if visible == self._visible_fields:
            return
        self._visible_fields = visible
        self.clock.pack_forget()
        self.bar.pack_forget()
        self.percent.pack_forget()
        if visible[0]:
            self.clock.pack(before=self.detail, pady=(0, 9))
        if visible[1]:
            self.bar.pack(before=self.detail, fill="x")
            self.percent.pack(side="right")

    def _refresh(self, packet):
        if self.model.refresh(packet):
            self.reason.configure(text=self.model.snapshot()["description"])
            self._visibility()
            self._paint()

    def _paint(self):
        snap = self.model.snapshot()
        if snap is None:
            return
        self.clock.configure(text=snap["time"] or "")
        percent = snap["percent"]
        self.percent.configure(text="" if percent is None else f'{round(percent)}% remaining')
        if percent is not None:
            width = max(1, self.bar.winfo_width())
            self.bar.coords(self.fill, 0, 0, round(width * percent / 100), 13)
            self.bar.itemconfigure(self.fill, fill=snap["bar_color"])

    def _poll(self):
        import pywintypes
        if self.dead:
            return
        try:
            # UI thread only, nonblocking, bounded reads from the service pipe.
            for _ in range(8):
                _, available, _ = self.win32pipe.PeekNamedPipe(self.pipe, 0)
                if not available:
                    break
                if available > MAX_PIPE_MESSAGE:
                    raise ValueError("Oversized service message")
                rc, raw = self.win32file.ReadFile(self.pipe, MAX_PIPE_MESSAGE)
                if rc != 0:
                    raise ValueError("Pipe read failed")
                packet = parse_popup(raw, self.device_id, retained=False)
                if packet["operation"] == "hide":
                    self.model.hide()
                    self.root.withdraw()
                elif packet["operation"] == "refresh":
                    self._refresh(packet)
                else:
                    self._upsert(packet)
            # Write event frames only after UI has processed the inbound state.
            while self.pending:
                self.win32file.WriteFile(self.pipe, self.pending[0])
                self.pending.pop(0)
            self._paint()
            self.root.after(POLL_MS, self._poll)
        except (OSError, ValueError, pywintypes.error):
            self.dead = True
            self.root.quit()
