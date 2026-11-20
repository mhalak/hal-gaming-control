"""Exercise foreground helper lifecycle without launching a real Windows process.

OS calls are mocked; the separate opt-in SYSTEM acceptance test remains required.
"""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json

import pytest

from gaming_control import focus_session as F
from gaming_control.foreground import IDLE, UNKNOWN


@pytest.fixture
def probe():
    p = F.FocusProbe()
    p.session, p.pid, p.process, p.started = 2, 123, Mock(), 10
    return p


@pytest.mark.parametrize("status, expected", [
    ("idle", IDLE), ("locked", IDLE), ("unknown", UNKNOWN),
])
def test_noninteractive_session_closes_probe(probe, status, expected):
    with patch.object(F, "selected_session", return_value=(2, status)), patch.object(probe, "close") as close:
        assert probe.read([]) == expected
    close.assert_called_once()


def test_new_session_replaces_existing_helper(probe):
    def close():
        probe.process = probe.session = None
    with patch.object(F, "selected_session", return_value=(3, "unlocked")), \
            patch.object(probe, "close", side_effect=close) as stop, \
            patch.object(probe, "_start") as start, \
            patch.object(F.time, "monotonic", return_value=20):
        assert probe.read([]) == UNKNOWN
    stop.assert_called_once()
    start.assert_called_once_with(3)
    assert probe.retry_after == 22


def test_child_exit_delays_restart(probe):
    def close():
        probe.process = probe.session = None
    with patch.object(F, "selected_session", return_value=(2, "unlocked")), \
            patch.object(probe, "_report_child_exit", return_value=True), \
            patch.object(probe, "close", side_effect=close) as stop, \
            patch.object(probe, "_start") as start, \
            patch.object(F.time, "monotonic", return_value=20):
        assert probe.read([]) == UNKNOWN
    stop.assert_called_once()
    start.assert_not_called()
    assert probe.retry_after == 22


@pytest.mark.parametrize("now, stalled", [(15, False), (15.01, True)])
def test_missing_sample_never_reuses_previous_state(probe, now, stalled):
    with patch.object(F, "selected_session", return_value=(2, "unlocked")), \
            patch.object(probe, "_report_child_exit", return_value=False), \
            patch.object(probe, "_receive", return_value=None), \
            patch.object(probe, "close") as close, \
            patch.object(probe, "_report_error") as report, \
            patch.object(F.time, "monotonic", return_value=now):
        assert probe.read([]) == UNKNOWN
    assert close.call_count == int(stalled)
    if stalled:
        report.assert_called_once_with("sample_timeout", 0)
        assert probe.retry_after == now + 2
    else:
        report.assert_not_called()


@pytest.mark.parametrize("second, expected", [
    ((2, "unlocked"), {"gaming_active": "ON", "active_game": "Test"}),
    ((3, "unlocked"), UNKNOWN), ((2, "locked"), IDLE),
])
def test_sample_invalidated_by_session_change(probe, second, expected):
    sample = {"time": 11, "status": "window"}
    active = {"gaming_active": "ON", "active_game": "Test"}
    rules = []
    with patch.object(F, "selected_session", side_effect=[(2, "unlocked"), second]), \
            patch.object(probe, "_report_child_exit", return_value=False), \
            patch.object(probe, "_receive", return_value=sample), \
            patch.object(F, "classify", return_value=active) as classify, \
            patch.object(probe, "close") as close, \
            patch.object(F.time, "monotonic", return_value=11.5):
        assert probe.read(rules) == expected
    classify.assert_called_once_with(sample, 2, 11.5, rules, session_lookup=F.process_session_id)
    assert close.call_count == int(second != (2, "unlocked"))
    assert probe.started == (11.5 if second == (2, "unlocked") else 10)


@pytest.mark.parametrize("child_exited", [True, False])
def test_probe_failure_is_unknown_and_rate_limited(probe, child_exited):
    error = OSError("synthetic failure")
    with patch.object(F, "selected_session", return_value=(2, "unlocked")), \
            patch.object(probe, "_report_child_exit", side_effect=[False, child_exited]) as exited, \
            patch.object(probe, "_receive", side_effect=error), \
            patch.object(probe, "_report_error") as report, \
            patch.object(probe, "close") as close, \
            patch.object(F.time, "monotonic", return_value=20):
        assert probe.read([]) == UNKNOWN
    assert exited.call_args.kwargs == {"wait_ms": 100}
    close.assert_called_once()
    assert probe.retry_after == 22
    if child_exited:
        report.assert_not_called()
    else:
        report.assert_called_once_with("probe", 0)


class WinError(Exception):
    def __init__(self, code):
        self.winerror = code


@pytest.fixture
def pipe_api(probe):
    probe.pipe = Mock()
    pipe = Mock()
    pipe.GetNamedPipeClientProcessId.return_value = probe.pid
    file = Mock()
    with patch.dict("sys.modules", {"pywintypes": SimpleNamespace(error=WinError),
                                    "win32pipe": pipe, "win32file": file}):
        yield pipe, file


def test_listening_pipe_has_no_sample(probe, pipe_api):
    pipe, file = pipe_api
    pipe.ConnectNamedPipe.side_effect = WinError(536)
    assert probe._receive() is None
    file.ReadFile.assert_not_called()


def test_pipe_rejects_unexpected_client_before_read(probe, pipe_api):
    pipe, file = pipe_api
    pipe.GetNamedPipeClientProcessId.return_value = 999
    with pytest.raises(ValueError, match="Unexpected foreground helper PID"):
        probe._receive()
    pipe.PeekNamedPipe.assert_not_called()
    file.ReadFile.assert_not_called()


def test_connected_pipe_returns_latest_sample(probe, pipe_api):
    pipe, file = pipe_api
    pipe.ConnectNamedPipe.side_effect = WinError(535)
    pipe.PeekNamedPipe.side_effect = [(0, 1, 0), (0, 1, 0), (0, 0, 0)]
    file.ReadFile.side_effect = [(0, json.dumps({"time": n}).encode()) for n in (10, 11)]
    assert probe._receive() == {"time": 11}
    assert file.ReadFile.call_count == 2


def test_pipe_reads_at_most_sixteen_messages(probe, pipe_api):
    pipe, file = pipe_api
    pipe.PeekNamedPipe.return_value = (0, 1, 0)
    file.ReadFile.return_value = (0, b'{"time":11}')
    assert probe._receive() == {"time": 11}
    assert file.ReadFile.call_count == 16


@pytest.mark.parametrize("rc, raw", [(1, b"{}"), (0, b"x" * 1025)])
def test_pipe_rejects_invalid_message(probe, pipe_api, rc, raw):
    pipe, file = pipe_api
    pipe.PeekNamedPipe.return_value = (0, 1, 0)
    file.ReadFile.return_value = (rc, raw)
    with pytest.raises(ValueError, match="Invalid foreground message"):
        probe._receive()
