from pathlib import Path

import pytest

from careeros.db import Database
from careeros.jobs.models import JobListing
from careeros.jobs.repository import JobRepository
from careeros.jobs.verification import VerificationResult


def _listing():
    return JobListing('fixture', 'one', 'Software Intern', 'Acme', 'Seattle, WA', 'internship',
                      'https://jobs.example/one', 'Build APIs', None, '2026-10-12T12:00:00+00:00',
                      source_url='https://source.example/one', application_url='https://apply.example/one',
                      requisition_id='REQ-1')


def test_migration_preserves_old_jobs_verifications_and_application_snapshots(tmp_path):
    import careeros.db
    database = Database(tmp_path / 'old.sqlite')
    migrations = Path(careeros.db.__file__).parent / 'migrations'
    with database.connect() as conn:
        conn.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY)')
        for migration in sorted(migrations.glob('[0-9][0-9][0-9]_*.sql')):
            if migration.name[:3] > '017':
                continue
            conn.executescript(migration.read_text())
            conn.execute('INSERT INTO schema_migrations VALUES(?)', (migration.name,))
        for identity, status in [('verified-job', 'verified'), ('held-job', 'held')]:
            conn.execute("INSERT INTO jobs(id,source,external_id,title,company,location,kind,url,description,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (identity, 'fixture', identity, 'Software Intern', 'Acme', 'Seattle, WA', 'internship', 'https://jobs.example/one', 'Build APIs', 'old-time'))
            conn.execute('INSERT INTO job_verifications VALUES(?,?,?,?,?,?,?)',
                         (identity, status, 'old reason', 'https://jobs.example/one', 'old-time', 'old text', 'old-fingerprint'))
        conn.execute("INSERT INTO resumes VALUES('resume','Resume','Real evidence','old-time','old-time')")
        conn.execute("INSERT INTO applications(id,job_id,resume_id,status,created_at,updated_at,snapshot_json,snapshot_hash) VALUES('application','verified-job','resume','needs_review','old-time','old-time','{\"frozen\":true}','old-hash')")
    database.initialize()
    database.initialize()  # Reopening an upgraded database must be harmless.
    with database.connect() as conn:
        assert dict(conn.execute('SELECT job_id,outcome,text,fingerprint FROM job_verifications WHERE job_id=?', ('verified-job',)).fetchone()) == {
            'job_id': 'verified-job', 'outcome': 'verified', 'text': 'old text', 'fingerprint': 'old-fingerprint'}
        assert conn.execute('SELECT outcome FROM job_verifications WHERE job_id=?', ('held-job',)).fetchone()[0] == 'insufficient_detail'
        application = conn.execute('SELECT * FROM applications').fetchone()
        assert (application['job_id'], application['snapshot_json'], application['snapshot_hash']) == ('verified-job', '{"frozen":true}', 'old-hash')
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 2


@pytest.mark.parametrize('outcome', ['verified', 'closed', 'identity_mismatch', 'insufficient_detail', 'access_restricted', 'not_found', 'transient_error', 'unsafe_destination'])
def test_persisted_verification_and_provenance_round_trip_idempotently(db, outcome):
    repository = JobRepository(db)
    repository.upsert_many([_listing()])
    job = repository.recent()[0]
    assert (job.application_url, job.requisition_id, job.fetched_at) == ('https://apply.example/one', 'REQ-1', '2026-10-12T12:00:00+00:00')
    result = VerificationResult('verified' if outcome == 'verified' else 'held', 'Reason',
                                'https://employer.example/one', '2026-10-13T12:00:00+00:00',
                                'Evidence text', 'fingerprint', outcome, 'https://jobs.example/one',
                                'Primary JSON-LD evidence', {'title': 'Software Intern', 'identifier': 'REQ-1'})
    for _ in range(2):
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            repository.save_verification(conn, job.id, result, attempts=1)
    persisted = repository.get_verification(job.id)
    assert persisted['outcome'] == outcome
    assert persisted['status'] == ('verified' if outcome == 'verified' else 'held')
    assert persisted['checked_url'] == 'https://jobs.example/one'
    assert persisted['final_url'] == 'https://employer.example/one'
    assert persisted['evidence_summary'] == 'Primary JSON-LD evidence'
    assert persisted['posting_evidence'] == {'title': 'Software Intern', 'identifier': 'REQ-1'}
    assert persisted['fingerprint'] == 'fingerprint'
    assert persisted['attempts'] == 1
    assert persisted['next_retry_at'] == ('2026-10-13T12:10:00+00:00' if outcome == 'transient_error' else None)
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM job_verifications').fetchone()[0] == 1


def test_retry_schedule_stops_at_three_automatic_attempts(db):
    repository = JobRepository(db)
    repository.upsert_many([_listing()])
    job = repository.recent()[0]
    result = VerificationResult('held', 'Temporary failure', None, '2026-10-13T12:00:00+00:00', outcome='transient_error')
    for attempts, retry in [(1, '2026-10-13T12:10:00+00:00'), (2, '2026-10-13T13:00:00+00:00'), (3, None)]:
        with db.connect() as conn:
            repository.save_verification(conn, job.id, result, attempts=attempts)
        assert repository.get_verification(job.id)['next_retry_at'] == retry
