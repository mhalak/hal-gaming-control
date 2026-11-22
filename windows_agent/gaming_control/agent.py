"""Poll sensors, execute explicit commands; never enforce a local quota."""
import logging
import time
from pathlib import Path
import psutil
import yaml
from .core import game_state, match_game, validate_rules
from .identity import resolve_identity
from .focus_session import FocusProbe, selected_session
from .targeted_terminate import terminate_verified
from .mqtt_bridge import Bridge
from .windows import system_uptime, lock_active_session, process_session_id
from .update_control import (submit_request, report_health, installed_version, read_status,
                             current_request_id)

LOG = logging.getLogger(__name__)


def scan(rules):
    if not rules:
        return []
    result = []
    # Create fresh Process objects to avoid psutil's process_iter PID cache.
    for pid in psutil.pids():
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                name = proc.name()
                candidates = [r for r in rules if r['process'].casefold() == name.casefold()]
                if not candidates:
                    continue
                info = {'name': name}
                if any('path_contains' in r for r in candidates):
                    info['exe'] = proc.exe()
                if any('command_line_arg' in r for r in candidates):
                    info['cmdline'] = proc.cmdline()
                game = match_game(info, candidates)
                if game:
                    result.append((proc, game, proc.create_time()))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def log_game_changes(games, previous):
    """Log process identities only on start/stop (including PID reuse)."""
    current = {(proc.pid, created, game): proc for proc, game, created in games}
    if previous is None:
        LOG.info('Initial live game scan: %s', game_state(game for _, _, game in current))
        previous = {}
    for (pid, created, game), proc in current.items():
        if (pid, created, game) in previous:
            continue
        try:
            exe = proc.exe()
        except (psutil.Error, OSError):
            exe = '<unavailable>'
        LOG.info('Game detected: %s pid=%s created_epoch=%s session=%s exe=%s',
                 game, pid, created, process_session_id(pid), exe)
    for pid, created, game in previous.keys() - current.keys():
        LOG.info('Game no longer detected: %s pid=%s created_epoch=%s', game, pid, created)
    return current


def stop_games(rules):
    # Scan at command execution, then recheck identity before killing.
    for previous, game, created in scan(rules):
        try:
            proc = psutil.Process(previous.pid)
            if proc.create_time() != created or not previous.is_running():
                continue
            candidates = [r for r in rules if r['name'] == game and
                          r['process'].casefold() == proc.name().casefold()]
            if not candidates:
                continue
            info = {'name': proc.name()}
            if any('path_contains' in r for r in candidates):
                info['exe'] = proc.exe()
            if any('command_line_arg' in r for r in candidates):
                info['cmdline'] = proc.cmdline()
            if match_game(info, candidates) == game and proc.is_running():
                proc.terminate()
                LOG.info('Termination requested: %s PID %s', game, proc.pid)
        except psutil.NoSuchProcess:
            pass
        except (psutil.AccessDenied, OSError):
            LOG.exception('Termination failed: %s PID %s', game, previous.pid)


def execute_targeted(offer, focus):
    """Re-read the user's foreground helper after authorization, then kill one PID.

    No process identity from the MQTT request is consulted. If the helper
    cannot provide a newer sample, deny rather than guessing.
    """
    try:
        focus.read([])  # forced fresh sampling; safe even without legacy rules
        return terminate_verified(
            offer['candidate'], getattr(focus, 'candidate', None),
            # A sample must be generated AFTER the command was received,
            # not merely after the old token was first offered.
            offered_sample=max(offer['sample_time'],
                               offer.get('received_at', offer['offered_at'])),
            current_sample=getattr(focus, 'last_sample_time', None),
            offered_at=offer['offered_at'], now=time.monotonic(),
            session=selected_session(), session_lookup=process_session_id)
    except (ValueError, TypeError, OSError):
        return False


def execute(command, rules):
    if command == 'terminate_game':
        if not rules:
            raise ValueError('Terminate game unavailable without local rules')
        stop_games(rules)
    elif command == 'lock_pc':
        lock_active_session()
    else:
        raise ValueError('Unknown command')


def confirm_health(bridge, data):
    """Write the health marker only after the broker acknowledged a QoS 1 publish.

    The marker carries the request that owns the current update transaction and this
    process identity, so the updater can tell the new process from a stale marker."""
    if not bridge.client.is_connected():
        return False
    try:
        evidence = bridge.client.publish(bridge.root + '/availability', 'online', qos=1, retain=True)
        evidence.wait_for_publish(timeout=2)
        if not evidence.is_published():
            return False
    except (RuntimeError, ValueError):
        LOG.warning('Update health PUBACK unavailable')
        return False
    report_health(data, installed_version(), request_id=current_request_id(data))
    return True


def dispatch_command(command, config_path, bridge, focus, rules):
    """Keep command handling separate from the telemetry polling state machine."""
    if isinstance(command, tuple) and command[0] == 'update':
        submit_request(Path(config_path).parent, command[1], installed_version())
    elif isinstance(command, tuple) and command[0] == 'terminate_target':
        success = execute_targeted(command[1], focus)
        bridge.publish_target_result(command[2], success)
    else:
        execute(command, rules)


def run(config_path, stop_event):
    config = yaml.safe_load(Path(config_path).read_text(encoding='utf-8'))
    interval = float(config.get('gaming', {}).get('check_interval_seconds', 1))
    if not 0.25 <= interval <= 5:
        raise ValueError('Interval must be between 0.25 and 5 seconds')
    rules = validate_rules(config.get('games', []))
    config = resolve_identity(config, config_path)
    bridge = Bridge(config)
    last_health = float('-inf')
    previous_games = None
    focus = FocusProbe()
    LOG.info('Agent starting: version=%s system_uptime=%s', installed_version(), system_uptime())
    try:
        bridge.start()
        while not stop_event.is_set():
            for command in bridge.drain_commands():
                if stop_event.is_set():
                    break
                try:
                    dispatch_command(command, config_path, bridge, focus, rules)
                except Exception:
                    LOG.exception('Command failed: %s', command)
            if stop_event.is_set():
                break
            games = scan(rules)
            previous_games = log_game_changes(games, previous_games)
            foreground_context = bridge.capture_foreground_context()
            active = focus.read(rules)
            values = game_state(name for _, name, _ in games) | active
            synchronized = bridge.publish(values, system_uptime())
            if synchronized:
                # Raw v2 identity is independent of legacy Windows game rules.
                # The old snapshot remains available during a safe HA cutover.
                bridge.publish_raw_foreground(
                    getattr(focus, "foreground_state", "unknown"),
                    getattr(focus, "candidate", None), foreground_context)
                if not rules:
                    bridge.publish_target_offer(
                        getattr(focus, "candidate", None), foreground_context,
                        sample_time=getattr(focus, "last_sample_time", None))
                bridge.publish_foreground(active, foreground_context)
                bridge.publish_candidate(getattr(focus, "candidate", None))
            if bridge.updates_enabled and synchronized and bridge.client.is_connected():
                if time.monotonic() - last_health >= 10:
                    if confirm_health(bridge, Path(config_path).parent):
                        last_health = time.monotonic()
                status = read_status(Path(config_path).parent)
                if status and bridge.last.get('_update_status') != status:
                    info = bridge.client.publish(bridge.root + '/update/status', status, qos=1, retain=True)
                    if info.rc == 0:
                        bridge.last['_update_status'] = status
            stop_event.wait(min(interval, 1.0))
    finally:
        focus.close()
        bridge.stop()
        LOG.info('Agent stopped')
