"""One-shot elevated updater; installed separately from the replaceable agent.

Transaction model (see docs/remote_update.md): a durable journal records the phase of the
swap; every start of this program first recovers an interrupted transaction from the
journal plus the actual layout of target/backup/staging, then handles a pending request.
The previous installation (backup) is deleted only after the new version proved healthy
and the journal says `committed`; cleanup afterwards can never cause a rollback.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from gaming_control.update_control import atomic_json, parse_request, version_tuple
from gaming_control.ota_trust import load_approved_staged, OtaTrustError

try:
    import msvcrt
    fcntl = None
except ImportError:  # POSIX (CI, tests)
    msvcrt = None
    import fcntl

LOG = logging.getLogger('updater')
NAME = 'SmartHouseGamingControl'
MAX_PACKAGE = 200 * 1024 * 1024
MAX_EXTRACTED = 600 * 1024 * 1024
MAX_MEMBERS = 20000
MAX_NAME = 240
USED_MAX = 256
PHASES = ('download', 'swap', 'installed', 'started', 'committed', 'restoring')
ARTIFACT = re.compile(r'windows-agent-(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(zip|json|sig)')
RESERVED = re.compile('CON|PRN|AUX|NUL|CONIN\\$|CONOUT\\$|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3]')
FORBIDDEN = re.compile(r'[<>:"\\|?*\x00-\x1f]')

# Every named point where tests simulate power loss / process death.
CRASH_POINTS = (
    'journal:download', 'staged', 'verified', 'journal:swap', 'stopped', 'renamed_backup',
    'renamed_payload', 'journal:installed', 'journal:started', 'service_started',
    'health_verified', 'journal:committed', 'status_success', 'cleanup_backup', 'cleanup_stage',
    'journal:restoring', 'recovery:target_removed', 'recovery:restored',
)


class LockBusy(Exception):
    """Another updater instance holds the lock."""


class ReplayRejected(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are not allowed')


# ------------------------------------------------------------------ network
def download(base, filename, target, limit):
    if not ARTIFACT.fullmatch(filename):
        raise ValueError('Only fixed release artifact names are allowed')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('A fixed HTTPS base URL is required')
    opener = urllib.request.build_opener(NoRedirect())
    deadline = time.monotonic() + 180
    with opener.open(base.rstrip('/') + '/' + filename, timeout=20) as response, target.open('wb') as out:
        count = 0
        while chunk := response.read(65536):
            count += len(chunk)
            if count > limit or time.monotonic() > deadline:
                raise ValueError('Download size or deadline exceeded')
            out.write(chunk)


def verify_manifest(raw, signature, public_key, version):
    key = serialization.load_pem_public_key(public_key)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError('Expected Ed25519 public key')
    key.verify(signature, raw)
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or set(manifest) != {'version', 'sha256', 'size', 'filename'}:
        raise ValueError('Invalid signed manifest')
    version_tuple(manifest['version'])
    if manifest['version'] != version or manifest['filename'] != f'windows-agent-{version}.zip':
        raise ValueError('Signed manifest version mismatch')
    if type(manifest['size']) is not int or not 0 < manifest['size'] <= MAX_PACKAGE:
        raise ValueError('Invalid package size')
    if not isinstance(manifest['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', manifest['sha256']):
        raise ValueError('Invalid manifest hash')
    return manifest


# ------------------------------------------------------------------ archive
def safe_segment(p):
    if not p or p in ('.', '..') or p.endswith(('.', ' ')) or FORBIDDEN.search(p):
        return False
    stem = p.split('.')[0].rstrip(' ').upper()
    return not RESERVED.fullmatch(stem)


def _canonical(name):
    return unicodedata.normalize('NFC', name).casefold()


def _unsafe_member_metadata(info, is_dir):
    """Reject encrypted, unsupported or special members and inconsistent file types."""
    mode = stat.S_IFMT(info.external_attr >> 16)
    return (info.flag_bits & 0x1                                   # encrypted
            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            or mode not in (0, stat.S_IFREG, stat.S_IFDIR)          # symlink, device, fifo ...
            or info.external_attr & 0x400                           # FILE_ATTRIBUTE_REPARSE_POINT
            or bool(info.external_attr & 0x10) != is_dir            # DOS directory flag vs name
            or (is_dir and mode == stat.S_IFREG) or (not is_dir and mode == stat.S_IFDIR))


def _check_member(info, seen_files, seen_dirs):
    """Validate one ZIP member; raises ValueError. Returns (is_dir, path parts)."""
    name = info.orig_filename  # ZipInfo.filename normalizes backslashes on Windows; validate the original
    is_dir = name.endswith('/')
    parts = name.rstrip('/').split('/')
    if (not name or len(name) > MAX_NAME or not all(safe_segment(p) for p in parts)
            or _unsafe_member_metadata(info, is_dir)):
        raise ValueError('Unsafe archive member')
    canonical = tuple(_canonical(p) for p in parts)
    if any(canonical[:depth] in seen_files for depth in range(1, len(canonical))):
        raise ValueError('Archive member below a file')
    if canonical in seen_files or (canonical in seen_dirs and not is_dir):
        raise ValueError('Duplicate archive member')
    (seen_dirs if is_dir else seen_files).add(canonical)
    seen_dirs.update(canonical[:depth] for depth in range(1, len(canonical)))
    return is_dir, parts


def copy_limited(source, out, declared, budget):
    """Copy a member and measure the bytes that really arrive; header sizes are not trusted."""
    count = 0
    while chunk := source.read(65536):
        count += len(chunk)
        if count > declared or count > budget:
            raise ValueError('Archive member larger than declared or over the extraction budget')
        out.write(chunk)
    if count != declared:
        raise ValueError('Archive member shorter than declared')
    return count


def extract_package(archive, target):
    """Validate every member first, then extract member by member (never the bulk helper)."""
    target = Path(target)
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if not infos or len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_EXTRACTED:
            raise ValueError('Archive size or member limit exceeded')
        seen_files, seen_dirs = set(), set()
        plan = [(info, *_check_member(info, seen_files, seen_dirs)) for info in infos]
        budget = MAX_EXTRACTED
        for info, is_dir, parts in plan:
            destination = target.joinpath(*parts)
            if not destination.resolve().is_relative_to(target.resolve()):
                raise ValueError('Archive member escapes target')
            if is_dir:
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as source, destination.open('xb') as out:
                budget -= copy_limited(source, out, info.file_size, budget)


# --------------------------------------------------------------- SCM wrapper
def service(action):
    """Fixed scripts only; nothing from a request, manifest or archive reaches PowerShell."""
    powershell = Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    scripts = {
        'stop': f"$ErrorActionPreference='Stop'; if ((Get-Service '{NAME}').Status -ne 'Stopped') {{ Stop-Service -Name '{NAME}' }}; (Get-Service '{NAME}').WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))",
        'start': f"$ErrorActionPreference='Stop'; if ((Get-Service '{NAME}').Status -ne 'Running') {{ Start-Service -Name '{NAME}' }}; (Get-Service '{NAME}').WaitForStatus('Running',[TimeSpan]::FromSeconds(30))",
        'check': f"$ErrorActionPreference='Stop'; if ((Get-Service '{NAME}').Status -ne 'Running') {{ throw 'Service is not running' }}",
    }
    if action not in scripts:
        raise ValueError('Unknown service action')
    subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', scripts[action]],
                   check=True, timeout=45, capture_output=True)


def process_start(pid):
    """Creation time of a live process, None when it is gone."""
    import psutil
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, OSError, TypeError, ValueError):
        return None


def wait_health(data, version, since, request_id=None, timeout=90, check=None,
                probe=process_start, clock=time.time, sleep=time.sleep):
    """Require a fresh marker from a live process started after `since`, bound to the request.

    request_id=None (rollback verification of the old version) does not demand a request binding."""
    check = check or (lambda: service('check'))
    deadline = clock() + timeout
    while True:
        try:
            health = json.loads((data / 'agent-health.json').read_text(encoding='utf-8'))
            pid, started = health['pid'], health['process_start']
            bound = request_id is None or health['request_id'] == request_id
            fresh = (health['version'] == version and bound and health['mqtt_acked'] is True
                     and type(pid) is int and isinstance(started, float)
                     and health['timestamp'] >= since and started >= since - 2)
            if fresh:
                actual = probe(pid)
                if actual is not None and abs(actual - started) < 1:
                    check()
                    return
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            pass
        if clock() >= deadline:
            raise TimeoutError('No fresh connected agent health marker')
        sleep(2)


# ----------------------------------------------------------- lock and ledger
class UpdateLock:
    """Exclusive OS file lock: released by the kernel if the process dies, so never stale."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        handle = self.path.open('a+b')
        try:
            if msvcrt:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise LockBusy('Another updater is running') from None
        self.handle = handle
        return self

    def __exit__(self, *exc):
        try:
            if msvcrt:
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()
            self.handle = None


def claim_request_id(path, request, now):
    """Durably burn a request id before any work; bounded, expired entries are pruned."""
    try:
        ledger = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(ledger, dict):
            raise ValueError
    except FileNotFoundError:
        ledger = {}
    except ValueError:
        raise ValueError('Replay ledger unreadable') from None
    ledger = {key: expiry for key, expiry in ledger.items() if type(expiry) is int and expiry >= now}
    if request['request_id'] in ledger:
        raise ReplayRejected('Repeated request')
    if len(ledger) >= USED_MAX:
        raise ValueError('Replay ledger full')
    ledger[request['request_id']] = request['expires_at']
    atomic_json(path, ledger)


# ------------------------------------------------------------ status over MQTT
def updater_device_id(data, config):
    """Use the OS hostname, never YAML IDs or the old ProgramData/device_id.

    Keep the signature for the existing status reporter. A legacy YAML device
    section is rejected to prevent updates being sent under the wrong scope.
    """
    from gaming_control.identity import resolve_identity

    return resolve_identity(config, Path(data) / 'config.yaml')['device']['id']

class StatusReporter:
    """Separate MQTT client (own client id) so status is visible while the agent is stopped.

    The durable status file stays authoritative; this is delivery with PUBACK evidence.
    The newest status is re-published after every (re)connect."""

    def __init__(self, data, client_factory=mqtt.Client, connect_wait=3, flush_wait=10):
        self.client = None
        self.connected = threading.Event()
        self.delivered = threading.Event()
        self.lock = threading.Lock()
        self.last = None
        self.topic = None
        self.gave_up = False
        self.connect_wait = connect_wait
        self.flush_wait = flush_wait
        try:
            config = yaml.safe_load((Path(data) / 'config.yaml').read_text(encoding='utf-8'))
            cfg, device = config['mqtt'], updater_device_id(data, config)
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', device):
                raise ValueError('Invalid device id')
            self.topic = f'SmartHouse/Gaming/{device}/update/status'
            client = client_factory(mqtt.CallbackAPIVersion.VERSION2, client_id=f'gaming-updater-{device}',
                                    protocol=mqtt.MQTTv5)
            self.client = client
            if cfg.get('username'):
                password = os.environ[cfg['password_env']] if cfg.get('password_env') else cfg.get('password')
                client.username_pw_set(cfg['username'], password)
            if cfg.get('tls', False):
                client.tls_set(ca_certs=cfg.get('ca_certs'))
            client.reconnect_delay_set(1, 30)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.connect_async(cfg['host'], int(cfg.get('port', 1883)), 30, clean_start=True)
            client.loop_start()
        except Exception as err:  # never let reporting break an update
            LOG.warning('Status client unavailable: %s', type(err).__name__)
            self.close()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            return
        self.connected.set()
        with self.lock:
            last = self.last
        if last is not None:
            self._send(last)

    def _on_disconnect(self, *args):
        self.connected.clear()

    def _send(self, status):
        client = self.client
        if client is None:
            return False
        try:
            info = client.publish(self.topic, json.dumps(status), qos=1, retain=True)
            info.wait_for_publish(timeout=2)
            acked = bool(info.is_published())
        except (RuntimeError, ValueError, OSError):
            return False
        with self.lock:
            if status is self.last and acked:
                self.delivered.set()
        return acked

    def publish(self, status):
        """Returns True only when the broker acknowledged (PUBACK) this status."""
        if self.client is None:
            return False
        with self.lock:
            self.last = status
            self.delivered.clear()
        if not self.connected.is_set():
            if self.gave_up or not self.connected.wait(self.connect_wait):
                self.gave_up = True
                return False  # re-published from _on_connect once the broker is reachable
        return self._send(status)

    def close(self):
        client, self.client = self.client, None
        if client is None:
            return
        if self.last is not None and not self.delivered.is_set() and self.flush_wait:
            self.client = client  # on_connect keeps re-sending the newest status meanwhile
            self.delivered.wait(self.flush_wait)
            self.client = None
        try:
            client.disconnect()
            client.loop_stop()
        except Exception:
            pass


# ---------------------------------------------------------------- signed Windows binary trust
def verify_authenticode(executable, pinned_thumbprint):
    """Require a Windows-valid signature from the pre-provisioned publisher.

    The script is fixed code, not a string from MQTT. The path and pinned
    thumbprint are passed through private child-process environment values.
    Ed25519 additionally authenticates the *entire* ZIP, including DLLs/PYD.
    """
    if os.name != 'nt':
        raise ValueError('Windows Authenticode verification requires Windows')
    if (not isinstance(pinned_thumbprint, str)
            or not re.fullmatch(r'[A-Fa-f0-9]{40}', pinned_thumbprint)):
        raise ValueError('Pinned Authenticode signer thumbprint required')
    executable = Path(executable)
    if not executable.is_file() or executable.is_symlink():
        raise ValueError('Signed service executable is missing')
    script = ("$ErrorActionPreference='Stop';"
              "$s=Get-AuthenticodeSignature -LiteralPath $env:HAL_OTA_EXE;"
              "if($s.Status -ne 'Valid' -or $null -eq $s.SignerCertificate"
              " -or $s.SignerCertificate.Thumbprint -ne $env:HAL_OTA_CERT)"
              "{exit 2}")
    env = os.environ.copy()
    env['HAL_OTA_EXE'] = str(executable)
    env['HAL_OTA_CERT'] = pinned_thumbprint.upper()
    powershell = (Path(os.environ['SystemRoot']) / 'System32' /
                  'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
    subprocess.run([str(powershell), '-NoProfile', '-NonInteractive',
                    '-Command', script], env=env, capture_output=True,
                   timeout=30, check=True)
    return True


# ---------------------------------------------------------------- transaction
class Updater:
    """Update transaction with injectable collaborators (service, download, clock, health)."""

    def __init__(self, data, target, service, download, reporter, health, clock=time.time, hook=None,
                 authenticode=None):
        self.data, self.target = Path(data), Path(target)
        self.backup = self.target.with_name(NAME + '.rollback')
        self.stage = self.target.with_name(NAME + '.staging')
        self.request_path = self.data / 'update-request.json'
        self.status_path = self.data / 'update-status.json'
        self.journal_path = self.data / 'update-journal.json'
        self.ledger_path = self.data / 'update-used.json'
        self.service, self.download, self.reporter = service, download, reporter
        self.health, self.clock = health, clock
        self.hook = hook or (lambda name: None)
        self.authenticode = authenticode or verify_authenticode
        self.request_id = None
        self.version = None
        self.record = None

    # -- durable state --------------------------------------------------
    def status(self, state, detail=''):
        value = {'request_id': self.request_id, 'version': self.version, 'status': state,
                 'detail': detail, 'timestamp': int(self.clock())}
        atomic_json(self.status_path, value)
        try:
            self.reporter.publish(value)
        except Exception as err:
            LOG.warning('Status publish failed: %s', type(err).__name__)

    def phase(self, value, **extra):
        self.record.update(extra, phase=value)
        atomic_json(self.journal_path, self.record)
        self.hook('journal:' + value)

    @staticmethod
    def version_of(path):
        return (path / 'version.txt').read_text(encoding='utf-8').strip()

    def last_state(self):
        try:
            return json.loads(self.status_path.read_text(encoding='utf-8'))['status']
        except (OSError, ValueError, KeyError):
            return None

    # -- entry point ----------------------------------------------------
    def run(self):
        try:
            with UpdateLock(self.data / 'update.lock'):
                return self._run_locked()
        except LockBusy:
            return 'busy'
        finally:
            self.reporter.close()

    def _run_locked(self):
        if not self.request_path.exists() and not self.journal_path.exists():
            return 'idle'
        outcome = None
        if self.journal_path.exists():
            outcome = self.recover_from_journal()
            if outcome == 'failed_recovery_required':
                return outcome  # blocked: leave the request and all evidence untouched
        if self.request_path.exists():
            outcome = self.process_request()
        return outcome

    # -- request handling -----------------------------------------------
    def process_request(self):
        self.request_id = self.version = self.record = None
        try:
            request = parse_request(self.request_path.read_bytes(), self.clock())
        except Exception as err:
            return self.reject(err)
        self.request_id, self.version = request['request_id'], request['version']
        try:
            claim_request_id(self.ledger_path, request, self.clock())
        except ReplayRejected:
            self.request_path.unlink(missing_ok=True)  # never clobber the status of the first run
            return 'replay'
        except Exception as err:
            self.status('failed', type(err).__name__)
            self.request_path.unlink(missing_ok=True)
            return 'failed'
        try:
            self.transaction(request)
        except Exception as err:
            self.abort(type(err).__name__)
        # Not in a finally block: a killed process must leave request and journal for recovery.
        self.request_path.unlink(missing_ok=True)
        return self.last_state()

    def reject(self, err):
        try:
            os.replace(self.request_path, self.data / 'update-request.rejected.json')
        except OSError:
            self.request_path.unlink(missing_ok=True)
        self.status('failed', type(err).__name__)
        return 'failed'

    # -- forward path -----------------------------------------------------
    def transaction(self, request):
        version = request['version']
        current = self.version_of(self.target)
        if version_tuple(version) <= version_tuple(current):
            raise ValueError('Downgrade or same-version update rejected')
        if self.backup.exists() or self.stage.exists():
            raise ValueError('Untracked transaction files require administrator recovery')
        cfg = json.loads((self.data / 'updater.json').read_text(encoding='utf-8'))
        self.record = {'old': current, 'new': version, 'request_id': request['request_id']}
        self.phase('download')
        self.stage.mkdir()
        self.hook('staged')
        payload = self.fetch_and_verify(cfg, version)
        if cfg.get('mqtt_install_enabled') is True:
            self.authenticode(payload / (NAME + '.exe'),
                              cfg.get('authenticode_thumbprint'))
        self.hook('verified')
        self.status('stopping')
        self.phase('swap')
        self.service('stop')
        self.hook('stopped')
        self.status('installing')
        self.target.rename(self.backup)
        self.hook('renamed_backup')
        payload.rename(self.target)
        self.hook('renamed_payload')
        self.phase('installed')
        self.status('starting')
        since = self.clock()
        self.phase('started', started_at=since)
        self.service('start')
        self.hook('service_started')
        self.health(version, since, request['request_id'])
        self.hook('health_verified')
        self.commit()

    def fetch_and_verify(self, cfg, version):
        self.status('downloading')
        raw, sig, package = [self.stage / name for name in ('manifest.json', 'manifest.sig', 'package.zip')]
        if cfg.get('mqtt_install_enabled') is True:
            agent_config = yaml.safe_load((self.data / 'config.yaml').read_text(encoding='utf-8'))
            device_id = updater_device_id(self.data, agent_config)
            source, manifest_raw, signature, marker = load_approved_staged(
                self.data / 'ota-staging', device_id, version,
                cfg['public_key_pem'], now=self.clock())
            raw.write_bytes(manifest_raw)
            sig.write_bytes(signature)
            self.status('verifying')
            manifest = verify_manifest(
                manifest_raw, signature, cfg['public_key_pem'].encode(), version)
            shutil.copyfile(source, package)
            # Persist only a validated opaque transfer ID, never an MQTT path.
            # Crash recovery can then clean the quarantined evidence *after*
            # a verified commit without losing the journal's exact ownership.
            transfer_id = marker.name[len('ota-'):-len('.approved.json')]
            if not re.fullmatch(r'[0-9a-f]{32}', transfer_id):
                raise ValueError('Invalid authenticated OTA transfer ID')
            self.record['ota_transfer_id'] = transfer_id
            atomic_json(self.journal_path, self.record)
        else:
            base = cfg['base_url']
            self.download(base, f'windows-agent-{version}.json', raw, 4096)
            self.download(base, f'windows-agent-{version}.sig', sig, 256)
            self.status('verifying')
            manifest = verify_manifest(raw.read_bytes(), sig.read_bytes(), cfg['public_key_pem'].encode(), version)
            self.download(base, manifest['filename'], package, MAX_PACKAGE)
        with package.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        if package.stat().st_size != manifest['size'] or digest != manifest['sha256']:
            raise ValueError('Package integrity check failed')
        payload = self.stage / 'payload'
        payload.mkdir()
        extract_package(package, payload)
        if not (payload / (NAME + '.exe')).is_file() or self.version_of(payload) != version:
            raise ValueError('Package layout/version mismatch')
        return payload

    def commit(self):
        """Point of no return: the new version is verified; nothing below may roll back."""
        self.phase('committed')
        self.status('success')
        self.hook('status_success')
        self.cleanup()

    def cleanup(self):
        """Best effort. A failure leaves the committed journal so the next start retries."""
        try:
            if self.backup.exists():
                shutil.rmtree(self.backup)
            self.hook('cleanup_backup')
            if self.stage.exists():
                shutil.rmtree(self.stage)
            self.hook('cleanup_stage')
            transfer_id = (self.record or {}).get('ota_transfer_id')
            if transfer_id is not None:
                if not isinstance(transfer_id, str) or not re.fullmatch(r'[0-9a-f]{32}', transfer_id):
                    raise ValueError('Invalid OTA journal transfer ID')
                root = self.data / 'ota-staging'
                if not root.is_dir() or root.is_symlink():
                    raise ValueError('Protected OTA quarantine unavailable')
                for extension in ('.approved.json', '.staged'):
                    path = root / f'ota-{transfer_id}{extension}'
                    if path.is_symlink():
                        raise ValueError('OTA quarantine symlink is unsafe')
                    path.unlink(missing_ok=True)
            self.journal_path.unlink(missing_ok=True)
            return True
        except Exception as err:
            LOG.warning('Cleanup incomplete, will retry at next start: %s', type(err).__name__)
            return False

    # -- failure and recovery --------------------------------------------
    def abort(self, detail):
        """In-process failure: the journal (if any) decides how to get back to a good state."""
        if self.record is None or not self.journal_path.exists():
            self.status('failed', detail)
            return
        try:
            self.record = self.load_journal()
        except Exception as err:
            self.status('failed_recovery_required', type(err).__name__)
            return
        self.recover(detail)

    def load_journal(self):
        record = json.loads(self.journal_path.read_text(encoding='utf-8'))
        if (not isinstance(record, dict) or record.get('phase') not in PHASES
                or not all(isinstance(record.get(k), str) for k in ('old', 'new', 'request_id'))):
            raise ValueError('Unknown or damaged journal')
        return record

    def recover_from_journal(self):
        try:
            self.record = self.load_journal()
        except Exception as err:
            self.status('failed_recovery_required', type(err).__name__)
            return 'failed_recovery_required'
        self.request_id, self.version = self.record['request_id'], self.record['new']
        self.recover()
        return self.last_state()

    def recover(self, detail=None):
        """Bring target/backup/staging back to one verified installation, or stop and report."""
        record = self.record
        try:
            phase = record['phase']
            if phase == 'committed':
                if self.version_of(self.target) != record['new']:
                    raise ValueError('Committed target version mismatch')
                self.status('success')
                self.cleanup()
            elif phase == 'download':
                if self.version_of(self.target) != record['old'] or self.backup.exists():
                    raise ValueError('Unexpected transaction layout')
                self.finish('failed', detail or 'InterruptedTransaction')
            elif not (phase == 'started' and detail is None and self.try_finish_new()):
                self.rollback(detail or 'InterruptedTransaction')
        except Exception as err:
            LOG.error('Recovery failed: %s', type(err).__name__)
            self.status('failed_recovery_required', type(err).__name__)

    def try_finish_new(self):
        """After an interrupted start: keep the new version only if it proves healthy."""
        record = self.record
        try:
            if self.version_of(self.target) != record['new'] or not self.backup.exists():
                return False
            self.service('start')
            self.health(record['new'], record.get('started_at', 0), record['request_id'])
        except Exception:
            return False
        self.commit()
        return True

    def rollback(self, detail):
        record = self.record
        if self.backup.exists():
            if self.version_of(self.backup) != record['old']:
                raise ValueError('Backup version mismatch')
        elif self.version_of(self.target) != record['old']:
            raise ValueError('No verified previous version')
        swapped = self.backup.exists() or record['phase'] == 'restoring'
        self.status('rollback', detail)
        if record['phase'] != 'restoring':
            self.phase('restoring')
        if self.backup.exists():
            self.service('stop')
            if self.target.exists():
                shutil.rmtree(self.target)
                self.hook('recovery:target_removed')
            self.backup.rename(self.target)
            self.hook('recovery:restored')
        if self.version_of(self.target) != record['old'] or not (self.target / (NAME + '.exe')).is_file():
            raise ValueError('No verified previous version')
        since = self.clock()
        self.service('start')
        self.health(record['old'], since, None)
        self.finish('rolled_back' if swapped else 'failed', detail)

    def finish(self, state, detail):
        """Report first, then drop the journal; an undeletable stage keeps the journal for a retry."""
        self.status(state, detail)
        shutil.rmtree(self.stage, ignore_errors=True)
        if not self.stage.exists():
            self.journal_path.unlink(missing_ok=True)


def main():
    data = Path(os.environ['ProgramData']) / NAME
    target = Path(os.environ['ProgramFiles']) / NAME
    if not (data / 'update-request.json').exists() and not (data / 'update-journal.json').exists():
        return
    Updater(data, target, service, download, StatusReporter(data),
            lambda version, since, request_id: wait_health(data, version, since, request_id)).run()


if __name__ == '__main__':
    main()
