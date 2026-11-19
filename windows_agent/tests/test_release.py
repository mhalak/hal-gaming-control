import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from package_release import package
from updater import verify_manifest
from cryptography.hazmat.primitives import serialization
import zipfile

def test_release_layout(tmp_path):
    agent = tmp_path / 'dist/SmartHouseGamingControl'
    updater = tmp_path / 'dist/SmartHouseGamingUpdater'
    agent.mkdir(parents=True)
    updater.mkdir()
    (agent/'version.txt').write_text('0.2.0')
    (agent/'SmartHouseGamingControl.exe').write_bytes(b'agent')
    (updater/'SmartHouseGamingUpdater.exe').write_bytes(b'updater')
    for name in ('install.ps1','uninstall.ps1','install_helpers.ps1','config.example.yaml'):
        (tmp_path/name).write_text('sample')
    out = tmp_path/'out'
    key = Ed25519PrivateKey.generate()
    package(tmp_path,out,'0.2.0',key)
    public = key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    version = 'windows-agent-0.2.0'
    assert verify_manifest((out/(version+'.json')).read_bytes(),(out/(version+'.sig')).read_bytes(),public,'0.2.0')['filename'] == version+'.zip'
    with zipfile.ZipFile(out/(version+'.zip')) as z:
        assert set(z.namelist()) == {'version.txt','SmartHouseGamingControl.exe'}
    with zipfile.ZipFile(out/'windows-install-0.2.0.zip') as z:
        assert 'dist/SmartHouseGamingUpdater/SmartHouseGamingUpdater.exe' in z.namelist()
        assert 'install.ps1' in z.namelist()


def build_release(tmp_path, version='0.2.0'):
    agent = tmp_path / 'dist/SmartHouseGamingControl'
    updater = tmp_path / 'dist/SmartHouseGamingUpdater'
    (agent / '_internal').mkdir(parents=True)
    updater.mkdir()
    (agent/'version.txt').write_text(version)
    (agent/'SmartHouseGamingControl.exe').write_bytes(b'agent')
    (agent/'_internal'/'base_library.zip').write_bytes(b'lib')
    (updater/'SmartHouseGamingUpdater.exe').write_bytes(b'updater')
    for name in ('install.ps1','uninstall.ps1','install_helpers.ps1','config.example.yaml'):
        (tmp_path/name).write_text('sample')
    key = Ed25519PrivateKey.generate()
    package(tmp_path, tmp_path/'out', version, key)
    return tmp_path/'out', key


def test_release_agent_zip_passes_the_updaters_own_validation(tmp_path):
    from updater import extract_package
    out, key = build_release(tmp_path)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    manifest = verify_manifest((out/'windows-agent-0.2.0.json').read_bytes(), (out/'windows-agent-0.2.0.sig').read_bytes(), public, '0.2.0')
    zip_path = out/'windows-agent-0.2.0.zip'
    assert manifest['size'] == zip_path.stat().st_size
    payload = tmp_path/'payload'
    payload.mkdir()
    extract_package(zip_path, payload)
    assert (payload/'SmartHouseGamingControl.exe').read_bytes() == b'agent'
    assert (payload/'_internal'/'base_library.zip').is_file()


def test_install_bundle_ships_the_installer_helpers(tmp_path):
    out, _ = build_release(tmp_path)
    with zipfile.ZipFile(out/'windows-install-0.2.0.zip') as z:
        names = set(z.namelist())
    assert {'install.ps1', 'install_helpers.ps1', 'uninstall.ps1', 'config.example.yaml'} <= names
    assert 'check_powershell.ps1' not in names
