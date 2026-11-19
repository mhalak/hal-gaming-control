"""Administrative update request intake. No arbitrary URLs or executables."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

TASK = r'\SmartHouseGamingControlUpdate'
REPLAY_MAX = 256
VERSION_RE = re.compile(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})')


def version_tuple(value):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise ValueError('Expected numeric major.minor.patch')
    return tuple(map(int, value.split('.')))


def installed_version():
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    try:
        value = (root / 'version.txt').read_text(encoding='utf-8').strip()
        version_tuple(value)
        return value
    except FileNotFoundError:
        return '0.0.0'


def parse_request(payload, now=None):
    if len(payload) > 512:
        raise ValueError('Request too large')
    data = json.loads(payload)
    if not isinstance(data, dict) or set(data) != {'version', 'request_id', 'expires_at'}:
        raise ValueError('Invalid update schema')
    version_tuple(data['version'])
    request_id = data['request_id']
    if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
        raise ValueError('Expected canonical UUID')
    now = time.time() if now is None else now
    expires = data['expires_at']
    if type(expires) is not int or not now < expires <= now + 120:
        raise ValueError('Expired or excessively future request')
    return data


def atomic_json(path, value):
    """Durable replace: fsync the temp file, atomically replace, then fsync the directory."""
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == 'posix':  # directory entries cannot be fsynced on Windows
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def read_status(data):
    try:
        return (data / 'update-status.json').read_text(encoding='utf-8')
    except FileNotFoundError:
        return None


def submit_request(data, request, current):
    request = parse_request(json.dumps(request))
    if version_tuple(request['version']) <= version_tuple(current):
        raise ValueError('Only strictly newer versions are allowed')
    if not (data / 'updater.json').is_file():
        raise ValueError('Updater is not provisioned')
    replay_path = data / 'update-replay.json'
    try:
        seen = json.loads(replay_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        seen = {}
    seen = {key: expiry for key, expiry in seen.items() if expiry >= time.time()}
    if request['request_id'] in seen:
        raise ValueError('Repeated request')
    if len(seen) >= REPLAY_MAX:
        raise ValueError('Replay ledger full')
    pending = data / 'update-request.json'
    # Exclusive creation; never overwrite an in-progress transaction.
    with pending.open('x', encoding='utf-8') as handle:
        json.dump(request, handle)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        seen[request['request_id']] = request['expires_at']
        atomic_json(replay_path, seen)
        executable = Path(os.environ['SystemRoot']) / 'System32' / 'schtasks.exe'
        subprocess.run([str(executable), '/Run', '/TN', TASK], check=True,
                       capture_output=True, timeout=15)
    except Exception:
        pending.unlink(missing_ok=True)
        raise


def current_request_id(data):
    """Request that owns the running update transaction, if any (read from the journal)."""
    try:
        value = json.loads((data / 'update-journal.json').read_text(encoding='utf-8'))['request_id']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) else None


def report_health(data, version, request_id=None, pid=None, started=None):
    """Health evidence; call only after an MQTT publish was acknowledged (PUBACK)."""
    if pid is None:
        pid = os.getpid()
    if started is None:
        import psutil
        started = psutil.Process(pid).create_time()
    atomic_json(data / 'agent-health.json', {
        'version': version, 'timestamp': time.time(), 'request_id': request_id,
        'pid': pid, 'process_start': float(started), 'mqtt_acked': True})
