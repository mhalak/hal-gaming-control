"""Regression coverage for per-device restriction enforcement dispatch."""
from importlib import import_module


def gate():
    return import_module(
        "custom_components.hal_gaming_control.restriction_dispatch"
    ).RestrictionDispatch()


def test_relaunch_and_game_switch_rearm():
    g = gate()
    assert g.should_fire("a", "Roblox", "one", 0)
    assert not g.should_fire("a", "Roblox", "two", 1)
    assert not g.should_fire("a", None, None, 2)
    assert g.should_fire("a", "Roblox", "three", 3)
    assert g.should_fire("a", "Minecraft", "four", 4)


def test_late_offer_and_bounded_rate_retry():
    g = gate()
    assert not g.should_fire("a", "Roblox", None, 0)
    assert g.should_fire("a", "Roblox", "one", 1)
    assert not g.should_fire("a", "Roblox", "two", 5)
    assert not g.should_fire("a", "Roblox", "one", 6)
    assert g.should_fire("a", "Roblox", "two", 6)
    assert not g.should_fire("a", "Roblox", "two", 100)


def test_isolation_and_recovery():
    g = gate()
    assert g.should_fire("a", "Roblox", "one", 0)
    assert g.should_fire("b", "Roblox", "one", 0)
    assert not g.should_fire("a", None, None, 1)
    assert g.should_fire("a", "Roblox", "two", 2)
    assert not g.should_fire("b", "Roblox", "two", 2)


def test_removed_device_does_not_keep_dispatch_state():
    g = gate()
    assert g.should_fire("a", "Roblox", "one", 0)
    g.prune(set())
    assert g.should_fire("a", "Roblox", "two", 1)
