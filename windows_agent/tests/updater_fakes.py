"""Deterministic fakes for updater tests: no SCM, no network, no real clock."""
import io
import json
import subprocess
import uuid
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NAME = 'SmartHouseGamingControl'
NOW = 1000.0


class SimulatedCrash(BaseException):
    """Power loss / killed process: BaseException so no `except Exception` runs."""


class FakeService:
    """Stands in for the SCM wrapper service(action)."""

    def __init__(self):
        self.running = True
        self.calls = []
        self.fail = {}

    def __call__(self, action):
        self.calls.append(action)
        remaining = self.fail.get(action, 0)
        if remaining:
            self.fail[action] = remaining - 1
            raise subprocess.CalledProcessError(1, action)
        if action == 'stop':
            self.running = False
        elif action == 'start':
            self.running = True
        elif action == 'check' and not self.running:
            raise subprocess.CalledProcessError(1, action)


class FakeReporter:
    def __init__(self):
        self.statuses = []
        self.closed = False
        self.raises = False

    def publish(self, value):
        if self.raises:
            raise RuntimeError('broker down')
        self.statuses.append(value)
        return True

    def close(self):
        self.closed = True

    @property
    def states(self):
        return [s['status'] for s in self.statuses]


def install(path, version):
    (path / '_internal').mkdir(parents=True)
    (path / f'{NAME}.exe').write_bytes(b'exe-' + version.encode())
    (path / '_internal' / 'lib.dll').write_bytes(b'dll')
    (path / 'version.txt').write_text(version)


def zip_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in members.items():
            z.writestr(name, content)
    return buffer.getvalue()


def public_pem(key):
    return key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)


def signed_release(key, version, members=None):
    import hashlib
    if members is None:
        members = {f'{NAME}.exe': b'new-exe', 'version.txt': version, '_internal/lib.dll': b'dll'}
    package = zip_bytes(members)
    raw = json.dumps({'version': version, 'filename': f'windows-agent-{version}.zip',
                      'size': len(package), 'sha256': hashlib.sha256(package).hexdigest()},
                     sort_keys=True, separators=(',', ':')).encode()
    return {f'windows-agent-{version}.json': raw,
            f'windows-agent-{version}.sig': key.sign(raw),
            f'windows-agent-{version}.zip': package}


class Env:
    """A temporary ProgramData / ProgramFiles pair with an installed `old` version."""

    def __init__(self, tmp_path, old='1.0.0'):
        import updater
        self.updater_module = updater
        self.data = tmp_path / 'ProgramData' / NAME
        self.data.mkdir(parents=True)
        self.target = tmp_path / 'ProgramFiles' / NAME
        self.backup = self.target.with_name(NAME + '.rollback')
        self.stage = self.target.with_name(NAME + '.staging')
        self.old = old
        install(self.target, old)
        self.key = Ed25519PrivateKey.generate()
        (self.data / 'updater.json').write_text(json.dumps(
            {'base_url': 'https://mirror.example/win', 'public_key_pem': public_pem(self.key).decode()}))
        self.served = {}
        self.downloads = []
        self.service = FakeService()
        self.reporter = FakeReporter()
        self.points = []
        self.crash_at = None
        self.bad_health = set()
        self.health_calls = []

    # collaborators ---------------------------------------------------
    def download(self, base, filename, target, limit):
        self.downloads.append(filename)
        if filename not in self.served:
            raise FileNotFoundError(filename)
        target.write_bytes(self.served[filename])

    def health(self, version, since, request_id):
        self.health_calls.append((version, since, request_id))
        if version in self.bad_health or (self.target / 'version.txt').read_text() != version:
            raise TimeoutError('No fresh connected agent health marker')

    def hook(self, name):
        self.points.append(name)
        if name == self.crash_at:
            raise SimulatedCrash(name)

    def clock(self):
        return NOW

    def updater(self, **overrides):
        args = dict(service=self.service, download=self.download, reporter=self.reporter,
                    health=self.health, clock=self.clock, hook=self.hook)
        args.update(overrides)
        return self.updater_module.Updater(self.data, self.target, **args)

    # scenario helpers -------------------------------------------------
    def release(self, version, members=None):
        self.served.update(signed_release(self.key, version, members))

    def request(self, version, request_id=None, expires=1060, raw=None):
        request_id = request_id or str(uuid.uuid4())
        if raw is None:
            raw = json.dumps({'version': version, 'request_id': request_id, 'expires_at': expires})
        (self.data / 'update-request.json').write_bytes(raw if isinstance(raw, bytes) else raw.encode())
        return request_id

    @property
    def request_path(self):
        return self.data / 'update-request.json'

    @property
    def journal_path(self):
        return self.data / 'update-journal.json'

    def status(self):
        return json.loads((self.data / 'update-status.json').read_text())

    def version(self):
        return (self.target / 'version.txt').read_text()

    def journal(self):
        return json.loads(self.journal_path.read_text())

    def used_ids(self):
        return json.loads((self.data / 'update-used.json').read_text())

    def assert_settled(self, version, state):
        assert self.version() == version
        assert (self.target / f'{NAME}.exe').is_file()
        assert self.status()['status'] == state
        assert not self.journal_path.exists()
        assert not self.backup.exists() and not self.stage.exists()
        assert self.service.running
