"""Adversarial package tests: signed manifest fields and member-by-member extraction."""
import json
import stat
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import updater as U
from updater_fakes import public_pem

KEY = Ed25519PrivateKey.generate()
GOOD = {'version': '1.2.3', 'filename': 'windows-agent-1.2.3.zip', 'sha256': 'a' * 64, 'size': 123}


def signed(manifest):
    raw = json.dumps(manifest).encode()
    return raw, KEY.sign(raw)


@pytest.mark.parametrize('field, value', [
    ('sha256', 'A' * 64), ('sha256', 'a' * 63), ('sha256', 'a' * 65), ('sha256', 'g' * 64),
    ('sha256', 'a' * 63 + '\n'), ('sha256', ' ' + 'a' * 63), ('sha256', 123), ('sha256', None),
    ('size', 0), ('size', -1), ('size', True), ('size', 1.5), ('size', '123'),
    ('size', U.MAX_PACKAGE + 1),
    ('filename', 'windows-agent-1.2.3.zip/../x'), ('filename', 'https://evil.example/a.zip'),
    ('filename', 'windows-agent-1.2.4.zip'), ('filename', '..\\windows-agent-1.2.3.zip'),
    ('version', '1.2.4'), ('version', '1.2'), ('version', '01.2.3'),
])
def test_manifest_field_validation(field, value):
    raw, sig = signed(GOOD | {field: value})
    with pytest.raises(Exception):
        U.verify_manifest(raw, sig, public_pem(KEY), '1.2.3')


@pytest.mark.parametrize('manifest', [
    {k: v for k, v in GOOD.items() if k != 'sha256'},
    {k: v for k, v in GOOD.items() if k != 'size'},
    {k: v for k, v in GOOD.items() if k != 'filename'},
    GOOD | {'url': 'https://evil.example/x.zip'},
    GOOD | {'args': ['/c', 'calc']},
    [GOOD], 'text',
])
def test_manifest_requires_exactly_the_signed_fields(manifest):
    raw, sig = signed(manifest)
    with pytest.raises(Exception):
        U.verify_manifest(raw, sig, public_pem(KEY), '1.2.3')


def test_manifest_signed_by_other_key_rejected():
    raw, _ = signed(GOOD)
    with pytest.raises(Exception):
        U.verify_manifest(raw, Ed25519PrivateKey.generate().sign(raw), public_pem(KEY), '1.2.3')


def test_valid_manifest_passes():
    raw, sig = signed(GOOD)
    assert U.verify_manifest(raw, sig, public_pem(KEY), '1.2.3') == GOOD


# ---------------------------------------------------------------- extraction
def build(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for entry in entries:
            name, content = entry if isinstance(entry, tuple) else (entry, 'x')
            info = zipfile.ZipInfo(name)
            if info.filename != name:
                # Preserve the original bytes in negative fixtures on every host.
                info.filename = name
                name = info
            z.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)
    return path


def extract(tmp_path, entries):
    archive = build(tmp_path / 'p.zip', entries)
    target = tmp_path / 'payload'
    target.mkdir()
    U.extract_package(archive, target)
    return target


def rejects(tmp_path, entries):
    archive = build(tmp_path / 'p.zip', entries)
    target = tmp_path / 'payload'
    target.mkdir()
    with pytest.raises(ValueError):
        U.extract_package(archive, target)
    assert list(target.rglob('*')) == []  # validation happens before anything is written


HOSTILE = [
    '/absolute.txt', '\\\\server\\share\\x', 'C:/x', 'C:\\x', 'c:x', '../x', 'a/../b', './x', 'a/./b',
    'a\\b', 'dir//x', '',
    'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM9', 'LPT1', 'LPT9', 'con.txt', 'NUL.tar.gz',
    'dir/Aux.dll', 'dir/com3.log', 'dir/LPT\u00b2', 'COM\u00b9.txt', 'conin$', 'CONOUT$',
    'aux .txt', 'file.txt:stream', 'file.txt::$DATA', 'a:b', 'dir/x:y',
    'trailing.', 'dir/trailing.', 'trailing ', 'dir /x', 'bad<name', 'bad>name', 'bad|name',
    'bad?name', 'bad*name', 'bad"name', 'ctl\x01name', 'nul\x00byte',
    'x' * 300,
]


@pytest.mark.parametrize('name', HOSTILE)
def test_hostile_member_names(tmp_path, name):
    rejects(tmp_path, ['SmartHouseGamingControl.exe', name])


@pytest.mark.parametrize('entries', [
    ['a.txt', 'A.TXT'],
    ['dir/a.txt', 'DIR/A.txt'],
    ['a', 'A/b'],                      # file then directory with same casefold
    ['A/b', 'a'],                      # directory then file
    ['dir/', 'DIR'],                   # directory entry vs file
    ['x/y', 'x'],                      # file x clashes with implicit dir x
    ['stra\u00dfe.txt', 'STRASSE.txt'],  # casefold expansion
    ['caf\u00e9.txt', 'cafe\u0301.txt'],  # NFC/NFD duplicates
    ['a.txt', 'a.txt'],                # exact duplicate
])
def test_duplicates_by_casefold_and_file_vs_directory(tmp_path, entries):
    rejects(tmp_path, entries)


def zip_with_info(tmp_path, name, content=b'x', attr=0, flag=0, compress=zipfile.ZIP_STORED):
    path = tmp_path / 'p.zip'
    info = zipfile.ZipInfo(name)
    info.external_attr = attr
    info.compress_type = compress
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(zipfile.ZipInfo('SmartHouseGamingControl.exe'), b'x')
        z.writestr(info, content)
    if flag:
        raw = bytearray(path.read_bytes())
        # set the encryption bit in the central directory entry of the second member
        central = raw.rfind(b'PK\x01\x02')
        raw[central + 8] |= flag
        path.write_bytes(bytes(raw))
    return path


@pytest.mark.parametrize('attr, label', [
    (stat.S_IFLNK << 16 | 0o777 << 16, 'symlink'),
    (stat.S_IFIFO << 16, 'fifo'),
    (stat.S_IFCHR << 16, 'chardev'),
    (0x400, 'windows reparse point'),
    (0x400 | 0x20, 'reparse point + archive'),
    (0x10, 'directory attribute on a file name'),
])
def test_special_members_rejected(tmp_path, attr, label):
    archive = zip_with_info(tmp_path, 'link', attr=attr)
    target = tmp_path / 'payload'
    target.mkdir()
    with pytest.raises(ValueError):
        U.extract_package(archive, target)
    assert list(target.rglob('*')) == []


def test_encrypted_member_rejected(tmp_path):
    archive = zip_with_info(tmp_path, 'secret.bin', flag=0x1)
    target = tmp_path / 'payload'
    target.mkdir()
    with pytest.raises(ValueError):
        U.extract_package(archive, target)


def test_unsupported_compression_rejected(tmp_path):
    archive = zip_with_info(tmp_path, 'big.bin', compress=zipfile.ZIP_BZIP2)
    target = tmp_path / 'payload'
    target.mkdir()
    with pytest.raises(ValueError):
        U.extract_package(archive, target)


def test_member_count_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(U, 'MAX_MEMBERS', 3)
    rejects(tmp_path, [f'f{i}.txt' for i in range(4)])


def test_declared_total_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(U, 'MAX_EXTRACTED', 10)
    rejects(tmp_path, [('a.bin', b'x' * 6), ('b.bin', b'x' * 6)])


def test_actual_extracted_bytes_are_measured_not_trusted(tmp_path):
    class Stream:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        def read(self, n):
            return self.chunks.pop(0) if self.chunks else b''
    out = tmp_path / 'out'
    with out.open('wb') as handle:
        # header declared 4 bytes, stream delivers 8
        with pytest.raises(ValueError):
            U.copy_limited(Stream([b'abcd', b'efgh']), handle, declared=4, budget=100)
    with out.open('wb') as handle:
        with pytest.raises(ValueError):  # budget exhausted
            U.copy_limited(Stream([b'abcd', b'efgh']), handle, declared=8, budget=5)
    with out.open('wb') as handle:
        with pytest.raises(ValueError):  # shorter than declared
            U.copy_limited(Stream([b'ab']), handle, declared=4, budget=100)
    with out.open('wb') as handle:
        assert U.copy_limited(Stream([b'ab', b'cd']), handle, declared=4, budget=100) == 4


def test_lying_header_is_detected(tmp_path, monkeypatch):
    archive = build(tmp_path / 'p.zip', [('SmartHouseGamingControl.exe', b'x' * 1000)])
    real = zipfile.ZipFile.infolist

    def lying(self):
        infos = real(self)
        for info in infos:
            info.file_size = 10  # header claims 10 bytes, member really has 1000
        return infos
    monkeypatch.setattr(zipfile.ZipFile, 'infolist', lying)
    target = tmp_path / 'payload'
    target.mkdir()
    with pytest.raises(Exception):
        U.extract_package(archive, target)


def test_existing_files_are_never_overwritten(tmp_path):
    archive = build(tmp_path / 'p.zip', ['SmartHouseGamingControl.exe'])
    target = tmp_path / 'payload'
    target.mkdir()
    (target / 'SmartHouseGamingControl.exe').write_text('precious')
    with pytest.raises(Exception):
        U.extract_package(archive, target)
    assert (target / 'SmartHouseGamingControl.exe').read_text() == 'precious'


def test_extractall_is_never_used():
    import inspect
    assert 'extractall' not in inspect.getsource(U)


def test_valid_layout_extracts_exactly(tmp_path):
    target = extract(tmp_path, [('SmartHouseGamingControl.exe', b'exe'), ('version.txt', b'1.2.3'),
                                ('_internal/', b''), ('_internal/lib/safe.dll', b'dll'),
                                ('_internal/lib2/', b'')])
    assert (target / 'SmartHouseGamingControl.exe').read_bytes() == b'exe'
    assert (target / '_internal/lib/safe.dll').read_bytes() == b'dll'
    assert (target / '_internal/lib2').is_dir()


# ----------------------------------------------- downloader / service wrapper
@pytest.mark.parametrize('filename', [
    'https://evil.example/x.zip', '../windows-agent-1.0.0.zip', 'a/windows-agent-1.0.0.zip',
    'windows-agent-1.0.0.zip?x=1', 'windows-agent-1.0.0.exe', 'windows-agent-1.0.zip',
    'windows-agent-1.0.0.zip\n', ' windows-agent-1.0.0.zip', 'x.ps1', '',
])
def test_download_only_fixed_artifact_names(tmp_path, monkeypatch, filename):
    def no_network(*args, **kwargs):
        raise AssertionError('network must not be reached')
    monkeypatch.setattr(U.urllib.request, 'build_opener', no_network)
    with pytest.raises(ValueError):
        U.download('https://mirror.example/win', filename, tmp_path / 'out', 100)


@pytest.mark.parametrize('base', ['http://mirror.example/x', 'https://u:p@mirror.example/x',
                                  'https://mirror.example/x?a=1', 'https://mirror.example/x#f',
                                  'file:///etc/passwd', 'https:///x', ''])
def test_download_requires_plain_https_base(tmp_path, monkeypatch, base):
    monkeypatch.setattr(U.urllib.request, 'build_opener', lambda *a: (_ for _ in ()).throw(AssertionError))
    with pytest.raises(ValueError):
        U.download(base, 'windows-agent-1.0.0.zip', tmp_path / 'out', 100)


def test_service_runs_only_fixed_scripts(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    monkeypatch.setattr(U.subprocess, 'run', lambda args, **kw: calls.append((args, kw)))
    for action in ('stop', 'start', 'check'):
        U.service(action)
    assert len(calls) == 3
    for args, kw in calls:
        assert args[1:4] == ['-NoProfile', '-NonInteractive', '-Command'] and len(args) == 5
        assert kw['check'] is True and kw['timeout'] <= 60 and 'shell' not in kw
        assert "'SmartHouseGamingControl'" in args[4]
    with pytest.raises(ValueError):
        U.service('stop; calc')
    assert len(calls) == 3


@pytest.mark.parametrize('name, attr', [
    ('directory/', stat.S_IFREG << 16 | 0x10),
    ('file.bin', stat.S_IFDIR << 16),
    ('directory/', stat.S_IFDIR << 16),
    ('file.bin', stat.S_IFBLK << 16),
    ('file.bin', stat.S_IFSOCK << 16),
    ('file.bin', 0x400),
])
def test_member_type_and_directory_flags_rejected_without_mutating_index(name, attr):
    info = zipfile.ZipInfo(name)
    info.external_attr = attr
    files, dirs = {('previous.bin',)}, {('existing',)}
    with pytest.raises(ValueError, match='Unsafe archive member'):
        U._check_member(info, files, dirs)
    assert files == {('previous.bin',)}
    assert dirs == {('existing',)}


@pytest.mark.parametrize('name, attr, expected_dir', [
    ('item.bin', 0, False),
    ('item.bin', stat.S_IFREG << 16, False),
    ('folder/', 0x10, True),
    ('folder/', stat.S_IFDIR << 16 | 0x10, True),
])
@pytest.mark.parametrize('compression', [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_member_supported_types_and_compression(name, attr, expected_dir, compression):
    info = zipfile.ZipInfo(name)
    info.external_attr = attr
    info.compress_type = compression
    files, dirs = set(), set()
    assert U._check_member(info, files, dirs) == (expected_dir, [name.rstrip('/')])
    assert files == (set() if expected_dir else {(name,)})
    assert dirs == ({('folder',)} if expected_dir else set())


def test_member_length_boundary_and_original_name():
    files, dirs = set(), set()
    name = 'x' * U.MAX_NAME
    assert U._check_member(zipfile.ZipInfo(name), files, dirs) == (False, [name])
    for invalid in ('x' * (U.MAX_NAME + 1), 'dir\\file.bin'):
        info = zipfile.ZipInfo(invalid)
        # The normalized filename must not replace the original during validation.
        if '\\' in invalid:
            info.filename = 'dir/file.bin'
        with pytest.raises(ValueError, match='Unsafe archive member'):
            U._check_member(info, files, dirs)
    assert files == {(name,)}
    assert not dirs


def test_member_canonical_index_preserves_implicit_directory_and_rejects_conflict():
    files, dirs = set(), set()
    info = zipfile.ZipInfo('Folder/Child.bin')
    assert U._check_member(info, files, dirs) == (False, ['Folder', 'Child.bin'])
    explicit = zipfile.ZipInfo('FOLDER/')
    explicit.external_attr = stat.S_IFDIR << 16 | 0x10
    assert U._check_member(explicit, files, dirs) == (True, ['FOLDER'])
    with pytest.raises(ValueError, match='Duplicate archive member'):
        U._check_member(zipfile.ZipInfo('folder'), files, dirs)
    with pytest.raises(ValueError, match='Archive member below a file'):
        U._check_member(zipfile.ZipInfo('folder/CHILD.BIN/extra'), files, dirs)
    assert files == {('folder', 'child.bin')}
    assert dirs == {('folder',)}
