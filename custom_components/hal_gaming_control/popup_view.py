"""HA-authoritative automatic popup projection, separate from transport."""
import math

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .smart_policy import effective_snapshot, effective_summary

MODES = ("countdown_mode", "progress_mode", "description_mode")
LABELS = {"daily": "Daily budget", "weekly": "Weekly budget", "schedule": "Schedule limit",
          "penalty": "Gaming penalty"}


def automatic_patch(coordinator, options, *, v2):
    """Resolve only automatic fields, leaving manual anchors untouched."""
    if not any(options[mode] == "automatic" for mode in MODES):
        return {}
    data = coordinator.data or {}
    totals = data.get("totals", {})
    snapshot = effective_snapshot(
        coordinator.options, totals, dt_util.now(), coordinator.device_id,
        ready=data.get("ready") is True and coordinator.last_update_success)
    summary = effective_summary(snapshot, totals)
    if summary["budget_status"] != "limited":
        raise ServiceValidationError("Automatic popup requires a verified finite effective budget")
    seconds = math.ceil(summary["remaining_seconds"])
    if not 0 <= seconds <= 604800:
        raise ServiceValidationError("Resolved popup values exceed protocol bounds")
    running = seconds > 0 and ("schedule" in summary["limiting_sources"]
                               or data.get("active_game") not in (None, "idle"))
    patch = {}
    if options["countdown_mode"] == "automatic":
        patch["remaining_seconds"] = seconds
        if v2:
            patch["countdown_running"] = running
    if options["progress_mode"] == "automatic":
        percent = summary["remaining_percent"]
        if percent is None or not 0 <= percent <= 100:
            raise ServiceValidationError("Automatic progress requires verified usage")
        patch["progress_percent"] = percent
        if v2:
            patch["progress_seconds"] = seconds if running else None
    if options["description_mode"] == "automatic":
        patch["description"] = " / ".join(LABELS[source] for source in summary["limiting_sources"])
    return patch


def v2_initial(view, options):
    """Manual progress animates with a manual timer; otherwise remains fixed."""
    countdown, progress = options["countdown_mode"], options["progress_mode"]
    if countdown == "hidden":
        view.update(remaining_seconds=None, countdown_running=False)
    elif countdown == "manual":
        view["countdown_running"] = True
    if progress == "hidden":
        view.update(progress_percent=None, progress_seconds=None)
    elif progress == "manual":
        view["progress_seconds"] = view["remaining_seconds"] if countdown == "manual" else None
    return view
