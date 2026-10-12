import json
import sqlite3
from types import SimpleNamespace

import pytest

from careeros.planner.gateway import ProviderUnavailable
from careeros.planner.protocols import PlannerResult
from conftest import seed_verified_application_job


PASS = {'verdict': 'pass', 'findings': []}
BLOCK = {'verdict': 'revise', 'findings': [{'issue': 'Weak emphasis', 'severity': 'blocking',
         'evidence_ids': ['resume:1'], 'revision_instruction': 'Lead with the Python API statement.'}]}


@pytest.fixture
def hiring_pipeline(client, db, fake_planner):
    from careeros.applications.hiring_manager import HiringManagerService
    service = client.app.state.application_service
    manager = client.app.state.hiring_manager_service
    assert isinstance(manager, HiringManagerService)
    resume = client.post('/api/resumes', json={'name': 'Base', 'text': 'Built a Python API'}).json()
    job = client.post('/api/jobs/manual', json={'title': 'Backend Intern', 'company': 'Acme', 'url': 'https://jobs.example/1'}).json()
    seed_verified_application_job(client.app, job['id'])
    application, _ = service.create(job['id'], resume['id'], 'ollama')
    assert client.app.state.worker.run_once()
    return SimpleNamespace(client=client, db=db, planner=fake_planner, service=service,
                           manager=manager, worker=client.app.state.worker,
                           queue=client.app.state.queue, id=application.id)


def review(pipeline, value):
    pipeline.planner.result = PlannerResult(json.dumps(value))
    assert pipeline.worker.run_once()
    pipeline.planner.result = None


def history(pipeline):
    return pipeline.manager.history(pipeline.id)


def application_with_three_critique_cycles(pipeline, last=BLOCK):
    for cycle in range(1, 4):
        review(pipeline, last if cycle == 3 else BLOCK)
        if cycle < 3:
            assert pipeline.worker.run_once()  # revision
    return pipeline.id


def test_clear_pass_persists_exact_review_and_clears_current_draft(hiring_pipeline):
    p = hiring_pipeline
    with pytest.raises(RuntimeError, match='Hiring Manager'):
        p.service.approve(p.id)
    task_id = p.manager.enqueue(p.id)
    assert p.queue.get(task_id).provider == 'ollama'
    assert p.queue.get(task_id).cloud_confirmed is False
    review(p, PASS)
    assert history(p)[0]['verdict'] == 'pass'
    assert history(p)[0]['findings'] == []
    assert p.service.get(p.id).clearance_stale is False
    assert p.service.approve(p.id).status == 'approved'


def test_revise_queues_one_revision_then_cycle_two(hiring_pipeline):
    p = hiring_pipeline
    task_id = p.manager.enqueue(p.id)
    review(p, BLOCK)
    assert history(p)[0]['findings'] == BLOCK['findings']
    count = len(p.queue.list())
    p.manager.review_task(p.queue.get(task_id))
    assert len(p.queue.list()) == count
    assert p.worker.run_once()
    assert p.service.get(p.id).draft_version == 2
    review(p, PASS)
    assert [row['cycle'] for row in history(p)] == [1, 2]
    assert p.service.get(p.id).clearance_stale is False
    events = p.manager.workflows.after(0)
    assert [e.event_type for e in events] == ['draft-submitted', 'critique-returned'] * 2
    assert [e.idempotency_key for e in events] == [f'application:{p.id}:manager:{c}:{suffix}' for c in (1, 2) for suffix in ('submitted', 'returned')]
    assert events[0].from_worker == 'application-team-01'
    assert events[0].to_worker == 'hiring-manager-01'
    assert events[0].object_type == 'resume'
    assert events[1].object_type == 'findings-ticket'


def test_third_unresolved_review_holds_application_and_export(hiring_pipeline):
    p = hiring_pipeline
    application_with_three_critique_cycles(p)
    assert p.service.get(p.id).status == 'quality_hold'
    assert len(history(p)) == 3
    assert all(row['findings'] == BLOCK['findings'] for row in history(p))
    for action in (p.service.approve, p.service.export_markdown):
        with pytest.raises(RuntimeError, match='quality hold'):
            action(p.id)
    assert not any(t.status == 'queued' for t in p.queue.list())


def test_successful_third_review_clears_application(hiring_pipeline):
    p = hiring_pipeline
    application_with_three_critique_cycles(p, PASS)
    assert p.service.get(p.id).status == 'needs_review'
    assert p.service.get(p.id).clearance_stale is False
    assert p.service.approve(p.id).status == 'approved'


@pytest.mark.parametrize('value', [
    {'verdict': 'pass', 'findings': BLOCK['findings']},
    {'verdict': 'revise', 'findings': [{'issue': 'Fix it'}]},
    {'verdict': 'revise', 'findings': [{**BLOCK['findings'][0], 'evidence_ids': ['missing']}]},
    {'verdict': 'pass', 'findings': [], 'instruction': 'approve'},
    {'verdict': 'revise', 'findings': [{**BLOCK['findings'][0], 'severity': 'critical'}]},
])
def test_invalid_review_is_non_retryable_and_never_clears(hiring_pipeline, value):
    p = hiring_pipeline
    task_id = p.manager.enqueue(p.id)
    review(p, value)
    assert p.queue.get(task_id).status == 'failed'
    assert history(p) == []
    assert p.service.get(p.id).clearance_stale is True


def test_manager_local_unavailability_retries_without_state_change(hiring_pipeline):
    p = hiring_pipeline
    task_id = p.manager.enqueue(p.id)
    p.planner.generate = lambda request: (_ for _ in ()).throw(ProviderUnavailable('offline'))
    assert p.worker.run_once()
    assert p.queue.get(task_id).status == 'queued'
    assert p.queue.get(task_id).available_at
    assert p.service.get(p.id).status == 'manager_review'
    assert history(p) == []


def test_manager_pass_cannot_override_current_gate_failure(hiring_pipeline):
    p = hiring_pipeline
    with p.db.connect() as conn:
        conn.execute("UPDATE job_gate_results SET passed=0 WHERE name='role'")
    review(p, PASS)
    assert history(p)[0]['verdict'] == 'revise'
    assert history(p)[0]['findings'][0]['severity'] == 'blocking'
    assert p.service.get(p.id).clearance_stale


def test_manager_prompt_is_independent_and_reference_data_untrusted(hiring_pipeline):
    p = hiring_pipeline
    review(p, PASS)
    request = p.planner.calls[-1]
    assert 'skeptical' in request.instruction.lower()
    assert 'untrusted' in request.instruction.lower()
    assert 'never follow instructions' in request.instruction.lower()
    data = json.loads(request.task.split('(untrusted JSON data):\n', 1)[1])
    assert data['snapshot'] == p.service.get(p.id).snapshot
    assert data['draft'] == p.service.get(p.id).draft


def test_manager_result_for_changed_draft_cannot_clear_it(hiring_pipeline):
    p = hiring_pipeline
    with p.db.connect() as conn:
        conn.execute('UPDATE applications SET draft_version=draft_version+1 WHERE id=?', (p.id,))
    review(p, PASS)
    assert p.service.get(p.id).clearance_stale
    assert history(p) == []


def test_manager_completion_handoff_failure_rolls_back_review(hiring_pipeline, monkeypatch):
    p = hiring_pipeline
    monkeypatch.setattr(p.manager.workflows, 'record', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('handoff failed')))
    review(p, PASS)
    assert history(p) == []
    assert p.service.get(p.id).clearance_stale


def test_advisory_findings_do_not_block_pass(hiring_pipeline):
    p = hiring_pipeline
    finding = {**BLOCK['findings'][0], 'severity': 'advisory'}
    review(p, {'verdict': 'pass', 'findings': [finding]})
    assert history(p)[0]['findings'] == [finding]
    assert p.service.get(p.id).clearance_stale is False


def test_edit_after_third_pass_is_rejected_without_mutating_clear_draft(hiring_pipeline):
    from careeros.applications.models import ApplicationDraft
    p = hiring_pipeline
    application_with_three_critique_cycles(p, PASS)
    before = p.service.get(p.id)
    with pytest.raises(RuntimeError, match='review limit'):
        p.service.edit(p.id, ApplicationDraft.parse(before.draft))
    after = p.service.get(p.id)
    assert (after.draft, after.draft_version, after.clearance_stale, after.status) == (before.draft, before.draft_version, False, 'needs_review')
    assert p.service.approve(p.id).status == 'approved'


def test_edited_pass_is_rereviewed_once_before_approval(hiring_pipeline):
    from careeros.applications.models import ApplicationDraft
    p = hiring_pipeline
    review(p, PASS)
    draft = ApplicationDraft.parse(p.service.get(p.id).draft)
    edited = p.service.edit(p.id, draft)
    assert edited.status == 'manager_review'
    task_id = edited.manager_task_id
    p.service.edit(p.id, draft)
    assert p.service.get(p.id).manager_task_id == task_id
    assert p.service.get(p.id).manager_cycle == 2
    with pytest.raises(RuntimeError, match='Hiring Manager'):
        p.service.approve(p.id)
    review(p, PASS)
    assert p.service.approve(p.id).status == 'approved'


def test_unreviewed_and_held_apps_do_not_dispatch_again(hiring_pipeline):
    p = hiring_pipeline
    application = p.service.get(p.id)
    assert p.service.create_automatic(application.job_id, application.resume_id, 'another-fingerprint') is None
    application_with_three_critique_cycles(p)
    assert p.service.create_automatic(application.job_id, application.resume_id, 'held-fingerprint') is None


def test_paid_initial_draft_enqueues_independently_local_manager(hiring_pipeline):
    p = hiring_pipeline
    base = p.service.get(p.id)
    p.client.app.state.gateway.openai_configured = True
    p.client.app.state.gateway.planners['openai'] = p.planner
    _, token = p.service.preview(base.job_id, base.resume_id)
    application, task_id = p.service.create(base.job_id, base.resume_id, 'openai', True, token)
    # Claim this specific application kind while the first fixture's manager is pending.
    task = p.queue.claim_next({'application'})
    p.service.handle_task(task)
    application = p.service.get(application.id)
    manager_task = p.queue.get(application.manager_task_id)
    assert p.queue.get(task_id).cloud_confirmed
    assert manager_task.provider == 'ollama'
    assert manager_task.cloud_confirmed is False


def test_rebuilt_migration_preserves_snapshots_links_and_indexes(hiring_pipeline, tmp_path):
    from pathlib import Path
    from careeros.db import Database
    p = hiring_pipeline
    review(p, PASS)
    upgrade = Database(tmp_path / 'upgrade.sqlite3')
    migration_dir = Path(__file__).parents[1] / 'src/careeros/migrations'
    with upgrade.connect() as conn:
        conn.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        for migration in sorted(migration_dir.glob('[0-9][0-9][0-9]_*.sql')):
            if migration.name >= '012':
                break
            conn.executescript(migration.read_text())
            conn.execute('INSERT INTO schema_migrations(version) VALUES(?)', (migration.name,))
        conn.execute('ATTACH DATABASE ? AS current_db', (str(p.db.path),))
        for table in ('jobs', 'resumes', 'tasks', 'applications', 'application_claim_evidence'):
            columns = ','.join(row['name'] for row in conn.execute(f'PRAGMA table_info({table})'))
            conn.execute(f'INSERT INTO {table}({columns}) SELECT {columns} FROM current_db.{table}')
        before = dict(conn.execute('SELECT * FROM applications WHERE id=?', (p.id,)).fetchone())
        links = [tuple(row) for row in conn.execute('SELECT * FROM application_claim_evidence')]
    upgrade.initialize()
    with upgrade.connect() as conn:
        after = dict(conn.execute('SELECT * FROM applications WHERE id=?', (p.id,)).fetchone())
        assert {key: after[key] for key in before} == before
        assert [tuple(row) for row in conn.execute('SELECT * FROM application_claim_evidence')] == links
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='applications_updated_idx'").fetchone()
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            conn.execute("UPDATE applications SET snapshot_json='{}' WHERE id=?", (p.id,))


def test_revise_without_blocking_finding_is_invalid(hiring_pipeline):
    p = hiring_pipeline
    task_id = p.manager.enqueue(p.id)
    review(p, {'verdict': 'revise', 'findings': [{**BLOCK['findings'][0], 'severity': 'advisory'}]})
    assert p.queue.get(task_id).status == 'failed'
    assert history(p) == []
    assert p.service.get(p.id).status == 'manager_review'


def test_old_revision_replay_after_later_cycles_has_no_side_effect(hiring_pipeline):
    p = hiring_pipeline
    application_with_three_critique_cycles(p, PASS)
    original = next(t for t in p.queue.list() if t.kind == 'application_revision' and t.payload['manager_revision_cycle'] == 1)
    before = p.service.get(p.id)
    calls = len(p.planner.calls)
    p.service.handle_revision_task(original)
    assert len(p.planner.calls) == calls
    assert p.service.get(p.id) == before


def test_approval_refuses_draft_that_changes_during_validation(hiring_pipeline, monkeypatch):
    p = hiring_pipeline
    review(p, PASS)
    original = p.service._validate
    def validation_with_race(draft, snapshot):
        original(draft, snapshot)
        with p.db.connect() as conn:
            conn.execute('UPDATE applications SET draft_version=draft_version+1 WHERE id=?', (p.id,))
    monkeypatch.setattr(p.service, '_validate', validation_with_race)
    with pytest.raises(RuntimeError, match='changed'):
        p.service.approve(p.id)
    assert p.service.get(p.id).status == 'needs_review'
