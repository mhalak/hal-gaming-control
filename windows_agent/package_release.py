"""Create signed versioned agent update and first-install bundles."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import zipfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from gaming_control.update_control import version_tuple

def archive(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for source, name in entries:
            z.write(source, name)

def entries(root, prefix=''):
    return [(p, prefix + p.relative_to(root).as_posix())
            for p in sorted(root.rglob('*')) if p.is_file()]

def sign_manifest(path, version, key):
    raw = json.dumps({'version':version,'filename':path.name,
        'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},
        sort_keys=True, separators=(',',':')).encode()
    path.with_suffix('.json').write_bytes(raw)
    path.with_suffix('.sig').write_bytes(key.sign(raw))

def package(root, output, version, key):
    version_tuple(version)
    agent = root / 'dist' / 'SmartHouseGamingControl'
    updater = root / 'dist' / 'SmartHouseGamingUpdater'
    if (agent / 'version.txt').read_text(encoding='utf-8').strip() != version:
        raise ValueError('Build version mismatch')
    if not (agent / 'SmartHouseGamingControl.exe').is_file() or not (updater / 'SmartHouseGamingUpdater.exe').is_file():
        raise ValueError('Missing build')
    output.mkdir(parents=True, exist_ok=True)
    update = output / f'windows-agent-{version}.zip'
    archive(update, entries(agent))
    sign_manifest(update, version, key)
    install = output / f'windows-install-{version}.zip'
    files = entries(agent, 'dist/SmartHouseGamingControl/') + entries(updater, 'dist/SmartHouseGamingUpdater/')
    files += [(root / name,name) for name in ('install.ps1','install_helpers.ps1','uninstall.ps1','config.example.yaml')]
    archive(install, files)
    sign_manifest(install, version, key)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--version', required=True)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    key = serialization.load_pem_private_key(os.environ['WINDOWS_RELEASE_SIGNING_KEY'].encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Expected Ed25519 private key')
    package(Path(__file__).resolve().parent, args.output, args.version, key)
