"""Transaction, recovery, crash injection, request lifecycle and lock tests."""
import json
import shutil

import pytest

import updater as U
from updater_fakes import NAME, NOW, Env, SimulatedCrash


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def ready(env, version='2.0.0', **kwargs):
    env.release(version, **kwargs)
    return env.request(version)


# ---------------------------------------------------------------- happy path
def test_success_flow_and_status_sequence(env):
    rid = ready(env)
    assert env.updater().run() == 'success'
    env.assert_settled('2.0.0', 'success')
    assert env.reporter.states == ['downloading', 'verifying', 'stopping', 'installing',
                                   'starting', 'success']
    assert {s['request_id'] for s in env.reporter.statuses} == {rid}
    assert env.service.calls == ['stop', 'start']
    assert env.health_calls == [('2.0.0', NOW, rid)]
    assert not env.request_path.exists()
    assert rid in env.used_ids()
    assert env.reporter.closed


def test_idle_without_request_or_journal(env):
    assert env.updater().run() == 'idle'
    assert env.service.calls == [] and env.reporter.statuses == []


def test_reporter_failure_never_breaks_update(env):
    env.reporter.raises = True
    ready(env)
    assert env.updater().run() == 'success'
    env.assert_settled('2.0.0', 'success')


# ---------------------------------------------- cleanup must never roll back
def test_cleanup_failure_after_success_does_not_roll_back(env, monkeypatch):
    ready(env)
    real = shutil.rmtree

    def failing(path, *args, **kwargs):
        if str(path).endswith('.rollback'):
            raise PermissionError('antivirus holds a handle')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(U.shutil, 'rmtree', failing)
    assert env.updater().run() == 'success'
    assert env.version() == '2.0.0'
    assert env.status()['status'] == 'success'
    assert 'rollback' not in env.reporter.states and 'rolled_back' not in env.reporter.states
    assert env.service.calls == ['stop', 'start']
    assert env.journal()['phase'] == 'committed'
    assert env.backup.exists()
    # next run only finishes the cleanup, still never rolls back
    monkeypatch.setattr(U.shutil, 'rmtree', real)
    env.updater().run()
    env.assert_settled('2.0.0', 'success')
    assert env.service.calls == ['stop', 'start']


# --------------------------------------------------------- crash injection
EXPECTED = {
    # point: (final version, final status, state of new-version health irrelevant)
    'journal:download': ('1.0.0', 'failed'),
    'staged': ('1.0.0', 'failed'),
    'verified': ('1.0.0', 'failed'),
    'journal:swap': ('1.0.0', 'failed'),
    'stopped': ('1.0.0', 'failed'),
    'renamed_backup': ('1.0.0', 'rolled_back'),
    'renamed_payload': ('1.0.0', 'rolled_back'),
    'journal:installed': ('1.0.0', 'rolled_back'),
    'journal:started': ('2.0.0', 'success'),
    'service_started': ('2.0.0', 'success'),
    'health_verified': ('2.0.0', 'success'),
    'journal:committed': ('2.0.0', 'success'),
    'status_success': ('2.0.0', 'success'),
    'cleanup_backup': ('2.0.0', 'success'),
    'cleanup_stage': ('2.0.0', 'success'),
}


def test_every_crash_point_is_covered():
    assert set(U.CRASH_POINTS) == set(EXPECTED) | {'journal:restoring', 'recovery:target_removed', 'recovery:restored'}


@pytest.mark.parametrize('point', sorted(EXPECTED))
def test_crash_at_every_point_recovers_on_next_run(env, point):
    rid = ready(env)
    env.crash_at = point
    with pytest.raises(SimulatedCrash):
        env.updater().run()
    assert point in env.points
    env.crash_at = None
    env.updater().run()
    version, state = EXPECTED[point]
    env.assert_settled(version, state)
    assert env.status()['request_id'] == rid
    assert not env.request_path.exists()  # replayed leftover request consumed, not re-run
    assert env.service.calls.count('stop') <= 3


@pytest.mark.parametrize('point', ['journal:started', 'service_started', 'health_verified'])
def test_unverifiable_new_version_after_crash_is_rolled_back(env, point):
    ready(env)
    env.crash_at = point
    with pytest.raises(SimulatedCrash):
        env.updater().run()
    env.crash_at = None
    env.bad_health.add('2.0.0')
    env.updater().run()
    env.assert_settled('1.0.0', 'rolled_back')


@pytest.mark.parametrize('second', ['journal:restoring', 'recovery:target_removed', 'recovery:restored'])
def test_crash_during_recovery_is_itself_recoverable(env, second):
    ready(env)
    env.crash_at = 'journal:installed'
    with pytest.raises(SimulatedCrash):
        env.updater().run()
    env.crash_at = second
    with pytest.raises(SimulatedCrash):
        env.updater().run()
    env.crash_at = None
    env.updater().run()
    env.assert_settled('1.0.0', 'rolled_back')


def test_no_crash_point_ever_leaves_service_without_install(env):
    for point in sorted(EXPECTED):
        sub = Env(env.data.parent.parent / point.replace(':', '_'))
        ready(sub)
        sub.crash_at = point
        with pytest.raises(SimulatedCrash):
            sub.updater().run()
        # at the instant of the crash either target or backup holds a complete install
        holders = [p for p in (sub.target, sub.backup)
                   if (p / f'{NAME}.exe').is_file() and (p / 'version.txt').is_file()]
        assert holders, point


# ------------------------------------------------- stop / start failure paths
def test_stop_failure_restores_and_reports(env):
    rid = ready(env)
    env.service.fail['stop'] = 1
    env.updater().run()
    env.assert_settled('1.0.0', 'failed')
    assert env.status()['detail'] == 'CalledProcessError'
    assert env.status()['request_id'] == rid
    assert env.service.calls == ['stop', 'start']
    assert env.health_calls[-1][0] == '1.0.0'


def test_stop_and_start_failure_requires_administrator(env):
    ready(env)
    env.service.fail.update(stop=1, start=1)
    env.updater().run()
    assert env.status()['status'] == 'failed_recovery_required'
    assert env.version() == '1.0.0'
    assert env.journal_path.exists()


def test_failed_start_after_swap_rolls_back_with_verified_old_health(env):
    rid = ready(env)
    env.service.fail['start'] = 1
    env.updater().run()
    env.assert_settled('1.0.0', 'rolled_back')
    assert env.service.calls == ['stop', 'start', 'stop', 'start']
    assert env.status()['detail'] == 'CalledProcessError'
    assert env.health_calls == [('1.0.0', NOW, None)]
    assert 'rollback' in env.reporter.states


def test_failed_new_health_rolls_back_and_verifies_old(env):
    rid = ready(env)
    env.bad_health.add('2.0.0')
    env.updater().run()
    env.assert_settled('1.0.0', 'rolled_back')
    assert env.status()['detail'] == 'TimeoutError'
    assert [c[0] for c in env.health_calls] == ['2.0.0', '1.0.0']
    assert env.health_calls[0][2] == rid and env.health_calls[1][2] is None


def test_rollback_start_failure_preserves_evidence(env):
    ready(env)
    env.service.fail['start'] = 2
    env.updater().run()
    assert env.status()['status'] == 'failed_recovery_required'
    assert env.version() == '1.0.0'  # old install restored even though it will not start
    assert env.journal()['phase'] == 'restoring'


def test_unverified_old_health_after_rollback_is_retried_next_run(env):
    ready(env)
    env.bad_health.update({'1.0.0', '2.0.0'})
    env.updater().run()
    assert env.status()['status'] == 'failed_recovery_required'
    assert env.journal_path.exists() and env.version() == '1.0.0'
    env.bad_health.clear()
    env.updater().run()
    env.assert_settled('1.0.0', 'rolled_back')


# ------------------------------------------------- package validation paths
def test_tampered_signature_is_rejected_before_service_is_touched(env):
    ready(env)
    env.served['windows-agent-2.0.0.sig'] = b'\0' * 64
    env.updater().run()
    env.assert_settled('1.0.0', 'failed')
    assert env.service.calls == []


@pytest.mark.parametrize('mutate', ['truncate', 'append', 'bitflip'])
def test_package_integrity_mismatch(env, mutate):
    ready(env)
    package = env.served['windows-agent-2.0.0.zip']
    env.served['windows-agent-2.0.0.zip'] = {
        'truncate': package[:-5], 'append': package + b'x',
        'bitflip': package[:20] + bytes([package[20] ^ 1]) + package[21:]}[mutate]
    env.updater().run()
    env.assert_settled('1.0.0', 'failed')
    assert env.service.calls == []


@pytest.mark.parametrize('members', [
    {f'{NAME}.exe': b'x'},                                   # no version.txt
    {'version.txt': '2.0.0'},                                # no exe
    {f'{NAME}.exe': b'x', 'version.txt': '9.9.9'},           # wrong version
    {f'{NAME}.exe': b'x', 'version.txt': '2.0.0', '../evil.txt': b'x'},   # signed but hostile
    {f'{NAME}.exe': b'x', 'version.txt': '2.0.0', 'aux.txt': b'x'},
])
def test_signed_but_invalid_layout_is_rejected(env, members):
    ready(env, members=members)
    env.updater().run()
    env.assert_settled('1.0.0', 'failed')
    assert env.service.calls == []
    assert not (env.target.parent / 'evil.txt').exists()


def test_download_failure_leaves_installation_untouched(env):
    env.request('2.0.0')  # nothing served
    env.updater().run()
    env.assert_settled('1.0.0', 'failed')
    assert env.service.calls == []


@pytest.mark.parametrize('version', ['1.0.0', '0.9.0'])
def test_same_or_older_version_rejected(env, version):
    env.release(version)
    env.request(version)
    env.updater().run()
    env.assert_settled('1.0.0', 'failed')
    assert env.downloads == [] and env.service.calls == []


def test_untracked_transaction_directories_block_update_and_are_preserved(env):
    ready(env)
    env.backup.mkdir()
    (env.backup / 'keep.txt').write_text('evidence')
    env.updater().run()
    assert env.status()['status'] == 'failed'
    assert (env.backup / 'keep.txt').read_text() == 'evidence'
    assert env.service.calls == [] and env.version() == '1.0.0'


# ------------------------------------------------------ request lifecycle
def test_unparseable_request_is_rejected_not_executed(env):
    env.request('2.0.0', raw=b'{not json')
    env.updater().run()
    assert env.status()['status'] == 'failed'
    assert env.status()['request_id'] is None
    assert not env.request_path.exists()
    assert (env.data / 'update-request.rejected.json').read_bytes() == b'{not json'
    assert env.downloads == [] and env.service.calls == [] and not env.journal_path.exists()


@pytest.mark.parametrize('expires', [999, 1000, 1121, 5000])
def test_expiry_is_enforced_by_updater(env, expires):
    env.release('2.0.0')
    env.request('2.0.0', expires=expires)
    env.updater().run()
    assert env.status()['status'] == 'failed'
    assert env.downloads == [] and env.service.calls == []
    assert env.version() == '1.0.0'


def test_replay_is_rejected_even_when_status_file_is_deleted(env):
    rid = ready(env)
    env.updater().run()
    env.assert_settled('2.0.0', 'success')
    (env.data / 'update-status.json').unlink()
    env.release('3.0.0')
    env.request('3.0.0', request_id=rid)
    before = list(env.downloads)
    env.updater().run()
    assert env.downloads == before and env.version() == '2.0.0'
    assert not env.request_path.exists()
    assert not (env.data / 'update-status.json').exists()  # replay must not clobber status


def test_request_id_is_burned_before_any_download(env):
    rid = env.request('2.0.0')  # nothing served: download fails
    env.updater().run()
    assert rid in env.used_ids()


def test_used_id_ledger_is_bounded_and_prunes_expired(env):
    ledger = {f'id-{i}': 5000 for i in range(U.USED_MAX)}
    (env.data / 'update-used.json').write_text(json.dumps(ledger))
    ready(env)
    env.updater().run()
    assert env.status()['status'] == 'failed' and env.version() == '1.0.0'
    ledger = {f'id-{i}': 10 for i in range(U.USED_MAX)}  # long expired
    (env.data / 'update-used.json').write_text(json.dumps(ledger))
    env.request('2.0.0')
    env.updater().run()
    env.assert_settled('2.0.0', 'success')
    assert len(env.used_ids()) == 1


def test_unreadable_ledger_fails_closed(env):
    (env.data / 'update-used.json').write_text('garbage')
    ready(env)
    env.updater().run()
    assert env.status()['status'] == 'failed' and env.version() == '1.0.0'
    assert env.downloads == []


def test_second_updater_instance_is_locked_out_and_keeps_request(env):
    ready(env)
    with U.UpdateLock(env.data / 'update.lock'):
        assert env.updater().run() == 'busy'
    assert env.request_path.exists()
    assert env.reporter.statuses == [] and env.service.calls == [] and env.downloads == []
    assert env.updater().run() == 'success'


def test_update_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / 'update.lock'
    with U.UpdateLock(path):
        with pytest.raises(U.LockBusy):
            with U.UpdateLock(path):
                pass
    with U.UpdateLock(path):
        pass


# --------------------------------------------- recovery from damaged state
def test_corrupt_journal_blocks_everything_and_is_preserved(env):
    ready(env)
    env.journal_path.write_text('{"phase": "swa')
    env.updater().run()
    assert env.status()['status'] == 'failed_recovery_required'
    assert env.journal_path.read_text() == '{"phase": "swa'
    assert env.request_path.exists()  # not consumed while recovery is blocked
    assert env.service.calls == [] and env.downloads == []


def test_unknown_phase_requires_administrator(env):
    env.journal_path.write_text(json.dumps({'phase': 'bogus', 'old': '1.0.0', 'new': '2.0.0',
                                            'request_id': 'r'}))
    env.updater().run()
    assert env.status()['status'] == 'failed_recovery_required'
    assert env.journal_path.exists()


def test_backup_of_wrong_version_is_never_promoted(env):
    ready(env)
    env.crash_at = 'renamed_payload'
    with pytest.raises(SimulatedCrash):
        env.updater().run()
    (env.backup / 'version.txt').write_text('0.0.1')
    env.crash_at = None
    env.updater().run()
    assert env.status()['status'] == 'failed_recovery_required'
    assert env.backup.exists() and env.journal_path.exists()
    assert (env.target / 'version.txt').read_text() == '2.0.0'  # target not destroyed either


def test_recovery_then_new_valid_request_is_processed_in_same_run(env):
    ready(env, '2.0.0')
    env.crash_at = 'journal:installed'
    with pytest.raises(SimulatedCrash):
        env.updater().run()
    env.crash_at = None
    env.release('3.0.0')
    env.request('3.0.0')
    env.updater().run()
    env.assert_settled('3.0.0', 'success')
    assert [s for s in env.reporter.states if s == 'rolled_back']
