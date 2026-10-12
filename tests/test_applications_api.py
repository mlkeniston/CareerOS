from dataclasses import asdict

from conftest import seed_verified_application_job
from test_applications import evidence_draft


def application_inputs(client, verified=True):
    resume = client.post('/api/resumes', json={'name': 'Base', 'text': 'Built a Python API'}).json()
    job = client.post('/api/jobs/manual', json={'title': 'Backend Intern', 'company': 'Acme', 'url': 'https://jobs.example/1'}).json()
    if verified:
        seed_verified_application_job(client.app, job['id'])
    return {'job_id': job['id'], 'resume_id': resume['id'], 'provider': 'ollama'}


def test_application_cannot_enqueue_without_verified_passing_job(client):
    inputs = application_inputs(client, verified=False)
    response = client.post('/api/applications', json=inputs)
    assert response.status_code == 409
    assert 'verification' in response.json()['detail'].lower()
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    seed_verified_application_job(client.app, inputs['job_id'])
    with client.app.state.db.connect() as conn:
        conn.execute("UPDATE job_gate_results SET passed=0 WHERE job_id=? AND name='eligibility'", (inputs['job_id'],))
    assert client.post('/api/applications', json=inputs).status_code == 409


def test_manual_edit_revalidates_claims_and_stales_previous_clearance(client):
    started = client.post('/api/applications', json=application_inputs(client)).json()
    client.app.state.worker.run_once()
    client.app.state.worker.run_once()  # independent manager pass
    route = f"/api/applications/{started['id']}"
    before = client.get(route).json()
    invalid = asdict(evidence_draft('Built an AWS cluster', anchor='Built a Python API'))
    response = client.put(route + '/draft', json=invalid)
    assert response.status_code == 409
    assert client.get(route).json()['draft'] == before['draft']
    client.post(route + '/approve')
    with client.app.state.db.connect() as conn:
        conn.execute('UPDATE applications SET clearance_stale=0 WHERE id=?', (started['id'],))
    changed = client.put(route + '/draft', json=asdict(evidence_draft()))
    assert changed.status_code == 200
    assert changed.json()['status'] == 'manager_review'
    after = client.get(route).json()
    assert after['draft_version'] == before['draft_version'] + 1
    assert after['clearance_stale'] is True
    assert after['snapshot_hash'] == before['snapshot_hash']


def test_application_api_rejects_unknown_evidence_and_oversized_fields(client):
    started = client.post('/api/applications', json=application_inputs(client)).json()
    client.app.state.worker.run_once()
    route = f"/api/applications/{started['id']}/draft"
    assert client.put(route, json=asdict(evidence_draft(evidence_id='missing'))).status_code == 409
    value = asdict(evidence_draft())
    value['resume_text'] = 'x' * 30001
    assert client.put(route, json=value).status_code == 422


def test_cloud_preview_token_invalidates_on_employer_text_change(client):
    inputs = application_inputs(client)
    client.app.state.gateway.openai_configured = True
    client.app.state.gateway.planners['openai'] = client.app.state.fake_planner
    preview = client.post('/api/applications/preview', json=inputs).json()
    assert 'evidence' in preview['sent_data']
    with client.app.state.db.connect() as conn:
        conn.execute("UPDATE job_verifications SET text=text || ' Updated employer content' WHERE job_id=?", (inputs['job_id'],))
    response = client.post('/api/applications', json={**inputs, 'provider': 'openai', 'confirm_cloud': True, 'preview_token': preview['preview_token']})
    assert response.status_code == 409
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0


def test_manual_edit_requires_employer_verification_to_remain_valid(client):
    inputs = application_inputs(client)
    started = client.post('/api/applications', json=inputs).json()
    client.app.state.worker.run_once()
    client.app.state.worker.run_once()  # independent manager pass
    with client.app.state.db.connect() as conn:
        conn.execute("UPDATE job_verifications SET status='held' WHERE job_id=?", (inputs['job_id'],))
    response = client.put(f"/api/applications/{started['id']}/draft", json=asdict(evidence_draft()))
    assert response.status_code == 409
    assert 'verification' in response.json()['detail'].lower()


def test_cloud_preview_token_invalidates_on_selected_model_change(client):
    inputs = application_inputs(client)
    client.app.state.gateway.openai_configured = True
    fake = client.app.state.fake_planner
    fake.model = 'preview-model'
    client.app.state.gateway.planners['openai'] = fake
    preview = client.post('/api/applications/preview', json=inputs).json()
    assert preview['model'] == 'preview-model'
    fake.model = 'changed-model'
    response = client.post('/api/applications', json={**inputs, 'provider': 'openai', 'confirm_cloud': True, 'preview_token': preview['preview_token']})
    assert response.status_code == 409


def test_paid_revision_preview_binds_executing_model_and_requires_fresh_confirmation(client):
    inputs = application_inputs(client)
    started = client.post('/api/applications', json=inputs).json()
    client.app.state.worker.run_once()
    client.app.state.worker.run_once()  # independent manager pass
    fake = client.app.state.fake_planner
    fake.model = 'previewed-model'
    client.app.state.gateway.openai_configured = True
    client.app.state.gateway.planners['openai'] = fake
    route = f"/api/applications/{started['id']}/revision-preview"
    response = client.post(route, json={'provider': 'openai', 'findings': []})
    assert response.status_code == 200
    preview = response.json()
    assert preview['sent_data']['selected_provider'] == 'openai'
    assert preview['sent_data']['selected_model'] == 'previewed-model'
    calls = len(fake.calls)
    task_id = client.app.state.queue.enqueue('application_revision',
        {'application_id': started['id'], 'findings': [], 'revision_preview_token': preview['preview_token']}, 'openai', True)
    fake.model = 'changed-unpreviewed-model'
    client.app.state.worker.run_once()
    assert len(fake.calls) == calls
    assert client.app.state.queue.get(task_id).status == 'failed'
    assert client.app.state.queue.get(task_id).available_at is None
    fresh = client.post(route, json={'provider': 'openai', 'findings': []}).json()
    assert fresh['preview_token'] != preview['preview_token']
    assert fresh['sent_data']['selected_model'] == 'changed-unpreviewed-model'
    replacement = client.app.state.queue.enqueue('application_revision',
        {'application_id': started['id'], 'findings': [], 'revision_preview_token': fresh['preview_token']}, 'openai', True)
    client.app.state.worker.run_once()
    assert client.app.state.queue.get(replacement).status == 'needs_review'
    assert len(fake.calls) == calls + 1
    assert client.app.state.application_service.get(started['id']).model == 'changed-unpreviewed-model'


def test_revision_preview_binds_selected_provider_and_findings(client):
    inputs = application_inputs(client)
    started = client.post('/api/applications', json=inputs).json()
    client.app.state.worker.run_once()
    route = f"/api/applications/{started['id']}/revision-preview"
    first = client.post(route, json={'provider': 'openai', 'findings': []}).json()
    second = client.post(route, json={'provider': 'ollama', 'findings': []}).json()
    changed = client.post(route, json={'provider': 'openai', 'findings': [{'issue': 'New finding'}]}).json()
    assert first['preview_token'] != second['preview_token']
    assert first['preview_token'] != changed['preview_token']


def test_manual_edit_rejects_line_wrap_qualifier_bypass(client):
    inputs = application_inputs(client)
    client.put(f"/api/resumes/{inputs['resume_id']}", json={'name': 'Base', 'text': 'Not fluent in Python'})
    started = client.post('/api/applications', json=inputs).json()
    client.app.state.worker.run_once()
    route = f"/api/applications/{started['id']}"
    before = client.get(route).json()
    draft = {'resume_text': 'Not\nfluent in Python', 'cover_letter': 'fluent in Python',
             'answers': {'Skill': 'fluent in Python'}, 'next_steps': [],
             'claims': [{'claim_id': 'c1', 'text': 'Not\nfluent in Python', 'evidence_ids': ['resume:1'],
                         'quote_anchors': ['Not fluent in Python']}]}
    response = client.put(route + '/draft', json=draft)
    assert response.status_code == 409
    after = client.get(route).json()
    assert after['draft'] == before['draft']
    assert after['draft_version'] == before['draft_version']
