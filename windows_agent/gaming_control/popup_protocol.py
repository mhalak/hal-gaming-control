"""Strict device-scoped HA->Windows popup UI v1 contract.

The contract carries *presentation* data, never OS commands or budget authority.
No permissive v0/old-format compatibility parser is provided.
"""
import json
import math
import re
import time

MAX_BYTES = 4096
MAX_SEQUENCE = (1 << 63) - 1
MAX_REMAINING = 604800
PALETTE = frozenset(("neutral", "primary", "success", "warning", "danger"))
_ROOT = frozenset(("version", "device_id", "producer_epoch", "sequence",
                   "issued_at", "message_ttl_seconds",
                   "display_stale_after_seconds", "popup_id", "operation"))
_VIEW = frozenset(("heading", "description", "remaining_seconds",
                   "progress_percent", "buttons"))
_BUTTON = frozenset(("id", "text", "color"))
_TOKEN = re.compile(r"[0-9a-f]{32}", re.ASCII)
_BUTTON_ID = re.compile(r"[a-z][a-z0-9_]{0,31}", re.ASCII)
_DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}", re.ASCII)


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate popup field")
        result[key] = value
    return result


def _plain(value, maximum, *, empty=False):
    return (type(value) is str and (empty or bool(value.strip()))
            and len(value) <= maximum
            and all(ord(char) >= 32 and ord(char) != 127 for char in value))


def _token(value):
    return type(value) is str and _TOKEN.fullmatch(value) is not None


def valid_button(button):
    return (type(button) is dict and button.keys() == _BUTTON
            and type(button["id"]) is str
            and _BUTTON_ID.fullmatch(button["id"]) is not None
            and _plain(button["text"], 48)
            and type(button["color"]) is str
            and button["color"] in PALETTE)


def valid_view(view):
    if type(view) is not dict or view.keys() != _VIEW:
        return False
    remaining, percent, buttons = (view["remaining_seconds"],
                                   view["progress_percent"], view["buttons"])
    return (
        _plain(view["heading"], 100)
        and _plain(view["description"], 120, empty=True)
        and type(remaining) is int and 0 <= remaining <= MAX_REMAINING
        and type(percent) in (float, int) and math.isfinite(percent)
        and 0 <= percent <= 100
        and type(buttons) is list and len(buttons) <= 3
        and all(valid_button(row) for row in buttons)
        and len({row["id"] for row in buttons}) == len(buttons))


def validate_popup(packet, device_id, *, retained=False, now=None):
    """Fail closed on messages that must never open UI."""
    wall = time.time() if now is None else now
    if (type(packet) is not dict
            or packet.keys() not in (_ROOT, _ROOT | {"view"})
            or packet.get("version") != 1 or type(packet.get("version")) is not int
            or not _DEVICE_ID.fullmatch(device_id)
            or packet.get("device_id") != device_id
            or not _token(packet.get("producer_epoch"))
            or not _token(packet.get("popup_id"))
            or type(packet.get("sequence")) is not int
            or not 1 <= packet["sequence"] <= MAX_SEQUENCE
            or type(packet.get("issued_at")) is not int
            or type(packet.get("message_ttl_seconds")) is not int
            or not 1 <= packet["message_ttl_seconds"] <= 30
            or type(packet.get("display_stale_after_seconds")) is not int
            or not 15 <= packet["display_stale_after_seconds"] <= 3600
            or type(wall) not in (float, int) or not math.isfinite(wall)
            or not -2 <= wall - packet["issued_at"] <= packet["message_ttl_seconds"]
            or retained is not False):
        raise ValueError("Invalid or stale popup instruction")
    if packet["operation"] == "upsert":
        if packet.keys() != _ROOT | {"view"} or not valid_view(packet["view"]):
            raise ValueError("Invalid popup form")
    elif packet["operation"] == "hide":
        if packet.keys() != _ROOT:
            raise ValueError("Popup hide cannot carry a form")
    else:
        raise ValueError("Unsupported popup operation")
    return packet


def parse_popup(payload, device_id, *, retained=False, now=None):
    if not isinstance(payload, (str, bytes)) or not 0 < len(payload) <= MAX_BYTES:
        raise ValueError("Oversized or empty popup instruction")
    try:
        packet = json.loads(payload, object_pairs_hook=_no_duplicates)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid popup JSON") from exc
    return validate_popup(packet, device_id, retained=retained, now=now)


class PopupOrder:
    """Reject duplicates/reordered messages, including after HA epoch rotation."""

    def __init__(self):
        self.epoch = None
        self.sequence = 0
        self.issued_at = 0
        self.retired = []

    def reset(self):
        self.__init__()

    def accept(self, packet):
        epoch = packet["producer_epoch"]
        seq = packet["sequence"]
        issued = packet["issued_at"]
        if epoch == self.epoch:
            if seq <= self.sequence or issued < self.issued_at:
                return False
        elif epoch in self.retired or issued < self.issued_at:
            return False
        else:
            if self.epoch is not None:
                self.retired.append(self.epoch)
                self.retired = self.retired[-16:]
        self.epoch, self.sequence, self.issued_at = epoch, seq, issued
        return True


def make_event(device_id, popup_id, event_id, kind, button_id=None):
    """Validate helper response against the currently displayed form first."""
    if (not _DEVICE_ID.fullmatch(device_id)
            or not _token(popup_id) or not _token(event_id)
            or kind not in ("button", "closed")):
        raise ValueError("Invalid popup response")
    data = {"version": 1, "device_id": device_id, "popup_id": popup_id,
            "event_id": event_id, "kind": kind}
    if kind == "button":
        if type(button_id) is not str or _BUTTON_ID.fullmatch(button_id) is None:
            raise ValueError("Invalid response button ID")
        data["button_id"] = button_id
    elif button_id is not None:
        raise ValueError("Close response cannot have a button")
    return data


def valid_event(data, packet, device_id):
    """Service side: respond only to button IDs from *this* accepted popup."""
    if (type(data) is not dict
            or data.keys() not in (
                {"version", "device_id", "popup_id", "event_id", "kind"},
                {"version", "device_id", "popup_id", "event_id", "kind", "button_id"})
            or packet is None or packet["operation"] != "upsert"
            or type(data.get("version")) is not int or data["version"] != 1
            or data.get("device_id") != device_id
            or data.get("popup_id") != packet["popup_id"]
            or not _token(data.get("event_id"))):
        return False
    if data.get("kind") == "closed":
        return "button_id" not in data
    if data.get("kind") != "button" or not _BUTTON_ID.fullmatch(
            data.get("button_id") if type(data.get("button_id")) is str else ""):
        return False
    return data["button_id"] in {b["id"] for b in packet["view"]["buttons"]}
