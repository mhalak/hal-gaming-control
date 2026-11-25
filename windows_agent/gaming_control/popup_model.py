"""Presentation-only countdown state, independent of Windows and gaming policy."""
import math
import time

COLORS = {"green": "#40C296", "amber": "#F2B64F", "red": "#ED646B"}
BUTTON_COLORS = {
    "neutral": "#3C4B63", "primary": "#3C70BB", "success": "#27846B",
    "warning": "#A46C20", "danger": "#B54B52",
}


def clock_text(seconds):
    """Human-visible integer seconds, never a quota or ledger reading."""
    n = max(0, int(math.ceil(seconds)))
    hours, rem = divmod(n, 3600)
    minutes, secs = divmod(rem, 60)
    return (f"{hours}:{minutes:02d}:{secs:02d}" if hours
            else f"{minutes:02d}:{secs:02d}")


class PopupModel:
    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.packet = None
        self.start_seconds = 0
        self.start_percent = 0
        self.started = 0
        self.progress_started = 0
        self.progress_seconds = None
        self.countdown_running = False
        self.visible = False

    def _apply(self, view, stamp):
        if "remaining_seconds" in view:
            self.start_seconds = view["remaining_seconds"]
            self.countdown_running = view["countdown_running"]
            self.started = stamp
        if "progress_percent" in view:
            self.start_percent = view["progress_percent"]
            self.progress_seconds = view["progress_seconds"]
            self.progress_started = stamp

    def upsert(self, packet):
        self.packet = dict(packet, view=dict(packet["view"]))
        view = self.packet["view"]
        if packet["version"] == 1:
            view.update(countdown_running=True, progress_seconds=view["remaining_seconds"])
        self._apply(view, self.clock())
        self.visible = True

    def refresh(self, packet):
        """A presentation patch is never permission to show a window."""
        if (not self.visible or self.packet is None or self.packet["version"] != 2
                or packet["popup_id"] != self.packet["popup_id"]
                or packet["producer_epoch"] != self.packet["producer_epoch"]
                or packet["sequence"] <= self.packet["sequence"]):
            return False
        view = packet["view"]
        self._apply(view, self.clock())
        self.packet["view"].update(view)
        self.packet["sequence"] = packet["sequence"]
        return True

    def hide(self):
        self.visible = False

    def _remaining(self, stamp):
        if self.start_seconds is None:
            return None
        elapsed = max(0, stamp - self.started) if self.countdown_running else 0
        return max(0.0, self.start_seconds - elapsed)

    def _progress(self, stamp):
        if self.start_percent is None or self.progress_seconds is None:
            return self.start_percent
        if not self.progress_seconds:
            return 0.0
        elapsed = max(0, stamp - self.progress_started)
        return max(0.0, self.start_percent * (1 - elapsed / self.progress_seconds))

    def snapshot(self):
        if not self.visible or self.packet is None:
            return None
        stamp = self.clock()
        remaining = self._remaining(stamp)
        percent = self._progress(stamp)
        color = ("red" if remaining <= 600 else "amber" if remaining <= 1800 else "green"
                 ) if remaining is not None else "green"
        return {
            "time": clock_text(remaining) if remaining is not None else None,
            "remaining": remaining,
            "percent": percent,
            "bar_color": COLORS[color],
            "heading": self.packet["view"]["heading"],
            "description": self.packet["view"]["description"],
            "buttons": self.packet["view"]["buttons"],
            "popup_id": self.packet["popup_id"],
        }
