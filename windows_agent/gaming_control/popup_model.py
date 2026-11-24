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
        self.visible = False

    def upsert(self, packet):
        self.packet = packet
        self.start_seconds = packet["view"]["remaining_seconds"]
        self.start_percent = packet["view"]["progress_percent"]
        self.started = self.clock()
        self.visible = True

    def hide(self):
        self.visible = False

    def snapshot(self):
        if not self.visible or self.packet is None:
            return None
        elapsed = max(0, self.clock() - self.started)
        remaining = max(0.0, self.start_seconds - elapsed)
        percent = (max(0.0, min(100.0, self.start_percent *
                   remaining / self.start_seconds)) if self.start_seconds > 0 else 0.0)
        color = "red" if remaining <= 600 else "amber" if remaining <= 1800 else "green"
        return {
            "time": clock_text(remaining),
            "remaining": remaining,
            "percent": percent,
            "bar_color": COLORS[color],
            "heading": self.packet["view"]["heading"],
            "description": self.packet["view"]["description"],
            "buttons": self.packet["view"]["buttons"],
            "popup_id": self.packet["popup_id"],
        }
