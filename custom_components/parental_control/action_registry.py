"""Protocol capabilities. Adding a supported action adds it to the builder."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Action:
    label: str
    topic: str

ACTION_REGISTRY = {
    "terminate_game": Action("Terminate game", "terminate_game"),
    "lock_pc": Action("Lock PC", "lock_pc"),
}


def available_actions(advertised, selected=()):
    return [key for key in ACTION_REGISTRY if key in advertised and key not in selected]


def selected_actions(advertised, selected):
    return list(dict.fromkeys(key for key in selected if key in ACTION_REGISTRY and key in advertised))
