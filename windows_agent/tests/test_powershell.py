"""PowerShell syntax lint (the original build.ps1 shipped with an unterminated regex) and
installer preflight / ACL / opt-in contract. Needs pwsh or Windows PowerShell; both CI runners have one."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / 'data'
PS = os.environ.get('PWSH') or shutil.which('pwsh') or shutil.which('powershell')
needs_ps = pytest.mark.skipif(PS is None, reason='no PowerShell available')
SCRIPTS = sorted(ROOT.glob('*.ps1'))


def run_ps(*args):
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-File', *map(str, args)],
                            capture_output=True, text=True, timeout=120,
                            env=os.environ | {'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': '1'})
    return result


# ------------------------------------------------------------------ syntax
def test_expected_scripts_exist():
    names = {p.name for p in SCRIPTS}
    assert {'build.ps1', 'install.ps1', 'uninstall.ps1', 'install_helpers.ps1',
            'check_powershell.ps1'} <= names


@needs_ps
def test_every_powershell_script_parses():
    result = run_ps(ROOT / 'check_powershell.ps1', ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'without errors' in result.stdout


@needs_ps
def test_lint_detects_the_original_unterminated_regex(tmp_path):
    broken = tmp_path / 'build.ps1'
    broken.write_text("param([string]$Version = '0.0.0')\n$ErrorActionPreference = 'Stop'\n"
                      "if ($Version -notmatch '^(0|[1-9][0-9]{0,3})\\.(0|[1-9][0-9]{0,3})\n"
                      ") { throw 'Invalid version' }\nSet-Location $PSScriptRoot\n")
    result = run_ps(ROOT / 'check_powershell.ps1', broken)
    assert result.returncode == 1
    assert 'build.ps1' in result.stdout


@needs_ps
def test_lint_fails_when_nothing_is_found(tmp_path):
    assert run_ps(ROOT / 'check_powershell.ps1', tmp_path).returncode == 2


def test_build_script_has_no_duplicated_body():
    text = (ROOT / 'build.ps1').read_text()
    assert text.count("param(") == 1
    assert text.count('PyInstaller --noconfirm --clean --onedir --name SmartHouseGamingControl ') == 1
    assert text.count('Invalid version') == 1


def test_ci_workflows_lint_powershell_before_build():
    text = (ROOT.parent / '.github' / 'workflows' / 'windows-ci.yml').read_text()
    preflight = re.search(r'(?m)^\s*run:\s*\./check_powershell\.ps1\s+\.\s*$', text)
    assert preflight, 'Windows CI must validate PowerShell scripts'
    assert "if: runner.os == 'Windows'" in text[:preflight.start()]
    for build in re.finditer(r'(?i)\bbuild\.ps1\b', text):
        assert preflight.start() < build.start(), 'PowerShell validation must precede build'


# --------------------------------------------------------- installer contract
def top_level_commands(path):
    result = run_ps(DATA / 'ps_commands.ps1', path)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    return [value] if isinstance(value, str) else value


MUTATING = {'New-Item', 'Copy-Item', 'New-Service', 'Register-ScheduledTask', 'Set-Content',
            'icacls.exe', 'sc.exe', 'Start-Service', 'Remove-Item'}


@needs_ps
def test_installer_runs_preflight_before_any_change():
    commands = top_level_commands(ROOT / 'install.ps1')
    assert 'Test-InstallPreflight' in commands
    first = commands.index('Test-InstallPreflight')
    assert not MUTATING & set(commands[:first])
    assert MUTATING & set(commands[first:])


@needs_ps
def test_installer_checks_acls_of_every_privileged_location():
    commands = top_level_commands(ROOT / 'install.ps1')
    assert commands.count('Assert-ProtectedAcl') >= 3
    text = (ROOT / 'install.ps1').read_text()
    for variable in ('$data', '$target', '$updater'):
        assert re.search(r'Assert-ProtectedAcl\s+(-Path\s+)?' + re.escape(variable), text), variable


def test_updates_are_opt_in_and_config_is_preserved():
    text = (ROOT / 'install.ps1').read_text()
    assert '[switch]$EnableUpdates' in text and '[switch]$ReplaceConfig' in text
    assert re.search(r'if\s*\(\s*\$EnableUpdates\s*\)', text)
    config_copies = [line for line in text.splitlines() if "'config.yaml'" in line and 'Copy-Item' in line]
    assert config_copies and all('-Force' not in line for line in config_copies)
    assert text.index('Test-Path $existingConfig') < text.index(config_copies[0])


def test_installer_rolls_back_what_it_created_and_never_touches_data_on_failure():
    text = (ROOT / 'install.ps1').read_text()
    assert 'catch' in text and 'sc.exe delete' in text and 'Unregister-ScheduledTask' in text
    assert 'Remove-Item' not in text.split('catch', 1)[1] or '$data' not in text.split('catch', 1)[1]


def test_uninstall_refuses_unfinished_transaction_and_keeps_data():
    text = (ROOT / 'uninstall.ps1').read_text()
    assert 'update-journal.json' in text and '[switch]$Force' in text
    assert 'SmartHouseGamingControlUpdate' in text
    assert re.search(r'Remove-Item[^\n]*\$updater', text) and 'ProgramData' in text
    assert not re.search(r'Remove-Item[^\n]*\$data', text)


# ----------------------------------------------------------------- preflight
@pytest.fixture
def layout(tmp_path):
    source = tmp_path / 'dist' / 'SmartHouseGamingControl'
    source.mkdir(parents=True)
    (source / 'SmartHouseGamingControl.exe').write_text('exe')
    (source / 'version.txt').write_text('1.0.0')
    updater_source = tmp_path / 'dist' / 'SmartHouseGamingUpdater'
    updater_source.mkdir()
    (updater_source / 'SmartHouseGamingUpdater.exe').write_text('exe')
    config = tmp_path / 'config.yaml'
    config.write_text('device:\n  id: pc1\n  name: PC\nmqtt:\n  host: 192.0.2.10\n'
                      '  username: pc1\n  password: synthetic-test-password\nupdate:\n  enabled: false\n')
    key = tmp_path / 'update.pub'
    key.write_text('-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA\n-----END PUBLIC KEY-----\n')
    return {'source': str(source), 'config': str(config), 'target': str(tmp_path / 'pf' / 'App'),
            'data': str(tmp_path / 'pd' / 'App'), 'updater_source': str(updater_source),
            'updater_target': str(tmp_path / 'pf' / 'Upd'), 'enable': False, 'url': None,
            'key': None, 'service': False, 'replace': False, '_root': tmp_path}


def preflight(layout, tmp_path, **changes):
    values = layout | changes
    values.pop('_root')
    path = tmp_path / 'args.json'
    path.write_text(json.dumps(values))
    result = run_ps(DATA / 'ps_preflight.ps1', path)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def enabled(layout, **extra):
    config = Path(layout['config'])
    config.write_text(config.read_text().replace('enabled: false', 'enabled: true'))
    return {'enable': True, 'url': 'https://mirror.lan/win', 'key': str(layout['_root'] / 'update.pub')} | extra


@needs_ps
def test_preflight_accepts_default_install(layout, tmp_path):
    assert preflight(layout, tmp_path) == 'OK'


@needs_ps
def test_preflight_accepts_opt_in_install(layout, tmp_path):
    assert preflight(layout, tmp_path, **enabled(layout)) == 'OK'


def make_dirty(layout, name):
    path = Path(layout[name])
    path.mkdir(parents=True)
    (path / 'old.txt').write_text('x')


@needs_ps
@pytest.mark.parametrize('changes, expected', [
    ({'service': True}, 'service'),
    ({'config': 'MISSING'}, 'configuration'),
    ({'url': 'https://mirror.lan/win'}, 'EnableUpdates'),
    ({'key': 'x.pub'}, 'EnableUpdates'),
])
def test_preflight_rejects(layout, tmp_path, changes, expected):
    if changes.get('config') == 'MISSING':
        changes = {'config': str(tmp_path / 'nope.yaml')}
    result = preflight(layout, tmp_path, **changes)
    assert result.startswith('ERR') and expected.lower() in result.lower()
    assert not Path(layout['target']).exists() and not Path(layout['data']).exists()


@needs_ps
def test_preflight_rejects_missing_build_outputs(layout, tmp_path):
    Path(layout['source'], 'SmartHouseGamingControl.exe').unlink()
    assert 'build' in preflight(layout, tmp_path).lower()
    Path(layout['source'], 'SmartHouseGamingControl.exe').write_text('x')
    Path(layout['source'], 'version.txt').unlink()
    assert 'version.txt' in preflight(layout, tmp_path)


@needs_ps
def test_preflight_rejects_placeholder_config(layout, tmp_path):
    Path(layout['config']).write_text('mqtt:\n  host: REPLACE_WITH_BROKER_IP\n')
    assert 'placeholder' in preflight(layout, tmp_path).lower()


@needs_ps
def test_existing_configuration_is_used_and_preserved(layout, tmp_path):
    Path(layout['config']).write_text('mqtt:\n  host: REPLACE_WITH_BROKER_IP\n')
    data = Path(layout['data'])
    data.mkdir(parents=True)
    existing = 'device:\n  id: pc1\nmqtt:\n  host: 192.0.2.10\nupdate:\n  enabled: false\n'
    (data / 'config.yaml').write_text(existing)
    assert preflight(layout, tmp_path) == 'OK'
    assert (data / 'config.yaml').read_text() == existing


@needs_ps
@pytest.mark.parametrize('leftover', ['target', 'updater_target'])
def test_preflight_rejects_leftover_program_files(layout, tmp_path, leftover):
    make_dirty(layout, leftover)
    assert 'leftover' in preflight(layout, tmp_path, **enabled(layout)).lower()


@needs_ps
@pytest.mark.parametrize('leftover', ['App.rollback', 'App.staging'])
def test_preflight_rejects_unfinished_transactions(layout, tmp_path, leftover):
    Path(layout['target']).with_name(leftover).mkdir(parents=True)
    assert 'transaction' in preflight(layout, tmp_path).lower()


@needs_ps
def test_preflight_rejects_journal(layout, tmp_path):
    data = Path(layout['data'])
    data.mkdir(parents=True)
    (data / 'update-journal.json').write_text('{}')
    assert 'transaction' in preflight(layout, tmp_path).lower()


@needs_ps
@pytest.mark.parametrize('url', ['http://mirror.lan/win', 'https://u:p@mirror.lan/win',
                                 'https://mirror.lan/win?x=1', 'https://mirror.lan/win#f',
                                 'ftp://mirror.lan', 'not a url', ''])
def test_preflight_rejects_unsafe_update_urls(layout, tmp_path, url):
    result = preflight(layout, tmp_path, **enabled(layout, url=url))
    assert result.startswith('ERR')


@needs_ps
def test_preflight_rejects_bad_keys_and_missing_updater(layout, tmp_path):
    options = enabled(layout)
    assert preflight(layout, tmp_path, **(options | {'key': str(tmp_path / 'gone.pub')})).startswith('ERR')
    bad = tmp_path / 'bad.pub'
    bad.write_text('hello')
    assert 'public key' in preflight(layout, tmp_path, **(options | {'key': str(bad)})).lower()
    Path(layout['updater_source'], 'SmartHouseGamingUpdater.exe').unlink()
    assert 'updater' in preflight(layout, tmp_path, **options).lower()


@needs_ps
def test_preflight_requires_config_to_agree_with_opt_in(layout, tmp_path):
    assert 'update.enabled' in preflight(layout, tmp_path, enable=True, url='https://mirror.lan/win',
                                         key=str(tmp_path / 'update.pub'))
    config = Path(layout['config'])
    config.write_text(config.read_text().replace('enabled: false', 'enabled: true'))
    assert 'update.enabled' in preflight(layout, tmp_path)   # agent would accept commands, no updater


# ---------------------------------------------------------------------- ACLs
SYSTEM, ADMINS, USERS, AUTH, EVERYONE = 'S-1-5-18', 'S-1-5-32-544', 'S-1-5-32-545', 'S-1-5-11', 'S-1-1-0'
READ, WRITE_DATA, MODIFY, FULL, GENERIC_WRITE = 0x1200A9, 0x2, 0x1301BF, 0x1F01FF, 0x40000000


def acl(tmp_path, rules):
    path = tmp_path / 'rules.json'
    path.write_text(json.dumps([{'sid': s, 'rights': r, 'type': t} for s, r, t in rules]))
    result = run_ps(DATA / 'ps_acl.ps1', path)
    assert result.returncode == 0, result.stderr
    return [s for s in result.stdout.strip().split(',') if s]


@needs_ps
def test_acl_accepts_system_admin_write_and_user_read(tmp_path):
    assert acl(tmp_path, [(SYSTEM, FULL, 'Allow'), (ADMINS, FULL, 'Allow'), (USERS, READ, 'Allow')]) == []


@needs_ps
@pytest.mark.parametrize('sid, rights', [(USERS, WRITE_DATA), (USERS, MODIFY), (AUTH, MODIFY),
                                         (EVERYONE, FULL), (USERS, GENERIC_WRITE),
                                         (USERS, 0x10), (USERS, 0x40), (USERS, 0x10000),
                                         (USERS, 0x80000), (USERS, 0x10000000)])
def test_acl_flags_ordinary_principals_that_can_write(tmp_path, sid, rights):
    assert acl(tmp_path, [(SYSTEM, FULL, 'Allow'), (sid, rights, 'Allow')]) == [sid]


@needs_ps
def test_acl_ignores_deny_rules(tmp_path):
    assert acl(tmp_path, [(USERS, FULL, 'Deny'), (SYSTEM, FULL, 'Allow')]) == []
