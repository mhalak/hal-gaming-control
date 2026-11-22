"""Security regressions for device-scoped, single-target termination (#155)."""
import json
from unittest.mock import Mock

import psutil
import pytest

from gaming_control.targeted_terminate import (
    parse_target_request, terminate_verified,
)

CANDIDATE = ("RobloxPlayerBeta.exe", 410, 1122.5, 3, None)
REQUEST = {"version": 1, "device_id": "pc1", "epoch": "a" * 32,
           "token": "b" * 32, "request_id": "c" * 32}


def test_target_request_accepts_only_exact_scoped_capability():
    assert parse_target_request(json.dumps(REQUEST).encode(), "pc1", "a" * 32) == REQUEST
    for mutation in (
        {"device_id": "pc2"}, {"epoch": "d" * 32},
        {"version": True}, {"version": 2}, {"token": "nothex"},
        {"request_id": ""}, {"process": "explorer.exe"},
    ):
        with pytest.raises(ValueError):
            parse_target_request(json.dumps(REQUEST | mutation), "pc1", "a" * 32)
    for raw in (b"", b"{", b"[]" , b"x" * 513,
                b'{"version":1,"version":1}', b'{"token":"x"}'):
        with pytest.raises(ValueError):
            parse_target_request(raw, "pc1", "a" * 32)


def candidate_process(*, name="RobloxPlayerBeta.exe", exe="C:/Games/roblox.exe",
                      pid=410, created=1122.5, running=True, argv=None):
    p = Mock(pid=pid)
    p.name.return_value = name
    p.exe.return_value = exe
    p.create_time.return_value = created
    p.is_running.return_value = running
    p.cmdline.return_value = argv or ["javaw.exe", "net.minecraft.client.main.Main"]
    return p


def attempt(candidate=CANDIDATE, current=CANDIDATE, *, since=100.0,
            observed=100.3, now=100.4, session=(3, "unlocked"), proc=None,
            observed_session=3, own_pid=900):
    p = proc or candidate_process()
    allowed = terminate_verified(
        candidate, current, offered_sample=since, current_sample=observed,
        offered_at=100.0, now=now, session=session,
        process_factory=lambda pid: p,
        session_lookup=lambda pid: observed_session,
        own_pid=own_pid, system_root="C:/Windows")
    return allowed, p


def test_verified_single_process_termination():
    ok, proc = attempt()
    assert ok
    proc.terminate.assert_called_once_with()


@pytest.mark.parametrize("override", [
    {"current": None},
    {"current": ("RobloxPlayerBeta.exe", 411, 1122.5, 3, None)},
    {"current": ("RobloxPlayerBeta.exe", 410, 1123.5, 3, None)},
    {"current": ("RobloxPlayerBeta.exe", 410, 1122.5, 4, None)},
    {"current": ("javaw.exe", 410, 1122.5, 3, None)},
    {"observed": 100.0},
    {"observed": 99.9},
    {"now": 104.1},
    {"session": (3, "locked")},
    {"session": (4, "unlocked")},
    {"observed_session": 4},
    {"own_pid": 410},
])
def test_target_rejected_after_focus_session_or_time_change(override):
    ok, proc = attempt(**override)
    assert not ok
    proc.terminate.assert_not_called()


@pytest.mark.parametrize("proc", [
    candidate_process(created=88),
    candidate_process(name="other.exe"),
    candidate_process(exe="C:/Windows/System32/fake.exe"),
    candidate_process(running=False),
    candidate_process(pid=999),
    candidate_process(name="explorer.exe"),
])
def test_recheck_denies_process_reuse_and_system_paths(proc):
    ok, proc = attempt(proc=proc)
    assert not ok
    proc.terminate.assert_not_called()


def test_java_requires_safe_verified_signature():
    generic = ("javaw.exe", 410, 1122.5, 3, None)
    ok, proc = attempt(candidate=generic, current=generic, proc=candidate_process(name="javaw.exe"))
    assert not ok
    proc.terminate.assert_not_called()
    minecraft = ("javaw.exe", 410, 1122.5, 3,
                 {"kind": "java_class", "value": "net.minecraft.client.main.Main"})
    ok, proc = attempt(candidate=minecraft, current=minecraft, proc=candidate_process(name="javaw.exe"))
    assert ok
    proc.terminate.assert_called_once()
    proc = candidate_process(name="javaw.exe", argv=["javaw.exe", "org.example.Other"])
    ok, proc = attempt(candidate=minecraft, current=minecraft, proc=proc)
    assert not ok
    proc.terminate.assert_not_called()


def test_access_denied_does_not_terminate():
    proc = candidate_process()
    proc.exe.side_effect = psutil.AccessDenied(410)
    ok, proc = attempt(proc=proc)
    assert not ok
    proc.terminate.assert_not_called()
