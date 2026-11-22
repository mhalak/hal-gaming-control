"""Validate discovery metadata; never accept arbitrary action topics."""
import json
import re
from .const import ROOT
from .action_registry import ACTION_REGISTRY

def parse_discovery(topic, payload):
    match = re.fullmatch(ROOT + r"/([A-Za-z0-9_-]{1,64})/discovery", topic)
    if not match:
        raise ValueError("Invalid discovery topic")
    data = json.loads(payload)
    if not isinstance(data, dict) or type(data.get("protocol_version")) is not int or data["protocol_version"] != 1:
        raise ValueError("Unsupported protocol")
    if data.get("device_id") != match[1]:
        raise ValueError("Device ID mismatch")
    name = data.get("name")
    games = data.get("games")
    actions = data.get("actions")
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 100:
        raise ValueError("Invalid name")
    if not isinstance(games, list) or not all(isinstance(g, str) and 0 < len(g) <= 80 and g != "idle" and " | " not in g for g in games):
        raise ValueError("Invalid games")
    if not isinstance(actions, list) or not all(isinstance(a, str) for a in actions):
        raise ValueError("Invalid actions")
    return {"device_id": match[1], "name": name, "protocol_version": 1,
            "games": sorted(set(games)), "actions": [a for a in ACTION_REGISTRY if a in actions]}

def games_from_state(state):
    if state in (None, "", "idle", "unknown", "unavailable"):
        return frozenset()
    return frozenset(state.split(" | "))
