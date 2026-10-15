import pytest

from conftest import seed_verified_application_job
from careeros.jobs.models import JobListing


def test_eligibility_defaults_to_empty_and_round_trips_locally(client):
    assert client.get('/api/profile').json()['eligibility_facts'] == {}
    facts = {'work_authorization': 'United States', 'sponsorship': 'no', 'graduation': '2027-05', 'enrollment': 'yes'}
    response = client.put('/api/profile', json={'target_roles': ['Software Engineer'], 'eligibility_facts': facts})
    assert response.status_code == 200
    assert response.json()['eligibility_facts'] == facts
    assert client.get('/api/profile').json()['eligibility_facts'] == facts
    client.put('/api/profile', json={'name': 'Updated'})
    assert client.get('/api/profile').json()['eligibility_facts'] == facts


def test_profile_update_refreshes_cached_application_gates(client):
    job = client.post('/api/jobs/manual', json={
        'title': 'Software Engineer Intern', 'company': 'Acme', 'location': 'Phoenix, AZ',
        'url': 'https://jobs.example/role',
    }).json()
    seed_verified_application_job(client.app, job['id'])
    client.put('/api/profile', json={'target_roles': ['Software Engineer Internships'], 'preferred_locations': ['Virginia']})
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT passed FROM job_gate_results WHERE job_id=? AND name='location'", (job['id'],)).fetchone()['passed'] == 0
    client.app.state.job_repository.upsert_many([
        JobListing('fixture', f'filler-{index}', 'Filler', 'Example', 'Phoenix, AZ', 'other',
                   f'https://jobs.example/filler-{index}', '', '9999-01-01', '9999-01-01')
        for index in range(501)
    ])
    client.put('/api/profile', json={'target_roles': ['Software Engineer Internships'], 'preferred_locations': ['United States']})
    with client.app.state.db.connect() as conn:
        gates = {row['name']: row['passed'] for row in conn.execute('SELECT name,passed FROM job_gate_results WHERE job_id=?', (job['id'],))}
    assert gates['role'] == 1
    assert gates['location'] == 1


@pytest.mark.parametrize('facts', [{'work_authorization': True}, {'a': 'x' * 501}, {'': 'yes'}, {'a': ''}, {'a': 'x\0y'}, {str(i): 'yes' for i in range(21)}])
def test_profile_rejects_invalid_eligibility_facts(client, facts):
    response = client.put('/api/profile', json={'eligibility_facts': facts})
    assert response.status_code == 422
    assert client.get('/api/profile').json()['eligibility_facts'] == {}


def test_cloud_preview_discloses_eligibility_and_requires_new_confirmation(client):
    from careeros.jobs.models import JobListing
    client.app.state.job_repository.upsert_many([JobListing('fixture', '1', 'SWE Intern', 'Example', 'Remote', 'internship', 'https://jobs.example/role', 'Public role text', None, 'now')])
    job = client.app.state.job_repository.recent()[0]
    resume = client.app.state.resume_repository.create('Current', 'User evidence')
    client.put('/api/profile', json={'eligibility_facts': {'sponsorship': 'no'}})
    preview = client.post('/api/applications/preview', json={'job_id': job.id, 'resume_id': resume.id}).json()
    assert preview['sent_data']['profile']['eligibility_facts'] == {'sponsorship': 'no'}
    client.put('/api/profile', json={'eligibility_facts': {'sponsorship': 'yes'}})
    updated = client.post('/api/applications/preview', json={'job_id': job.id, 'resume_id': resume.id}).json()
    assert updated['preview_token'] != preview['preview_token']


def test_profile_rejects_ambiguous_fact_keys(client):
    assert client.put('/api/profile', json={'eligibility_facts': {'citizenship': 'Canada', ' Citizenship ': 'United States'}}).status_code == 422
