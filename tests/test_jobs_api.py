import httpx

from careeros.jobs.models import JobListing, SourceResult


class FakeJobSource:
    name = "fixture"
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
    def fetch(self, query):
        if self.error:
            raise self.error
        return self.result


def test_refresh_and_search_use_mock_source(client):
    listing = JobListing("fixture", "one", "Software Intern", "Acme", "Remote", "internship", "https://jobs.example/1", "Build APIs", None, "2026-10-09", True)
    client.app.state.job_sources = [FakeJobSource(SourceResult([listing], []))]
    refreshed = client.post("/api/jobs/refresh", json={"text": "intern"})
    assert refreshed.status_code == 200
    assert refreshed.json()["saved"] == 1
    assert len(client.get("/api/jobs?q=software").json()) == 1


def test_manual_job_is_saved_and_unsafe_url_is_rejected(client):
    payload = {"title": "Backend Intern", "company": "Acme", "location": "NYC", "kind": "internship", "url": "https://jobs.example/1", "description": "Build APIs"}
    result = client.post("/api/jobs/manual", json=payload)
    assert result.status_code == 201
    assert client.post(f"/api/jobs/{result.json()['id']}/save").status_code == 200
    payload["url"] = "javascript:alert(1)"
    assert client.post("/api/jobs/manual", json=payload).status_code == 422


def test_failed_refresh_keeps_cached_jobs(client):
    listing = JobListing("fixture", "one", "Software Intern", "Acme", "Remote", "internship", "https://jobs.example/1", "Build APIs", None, "2026-10-09", True)
    client.app.state.job_repository.upsert_many([listing])
    client.app.state.job_sources = [FakeJobSource(error=httpx.ConnectTimeout("timeout"))]
    result = client.post("/api/jobs/refresh", json={}).json()
    assert result["sources"][0]["error"]
    assert len(client.get("/api/jobs?q=intern").json()) == 1


def test_unexpected_refresh_parser_error_keeps_cached_jobs(client):
    cached = JobListing("fixture", "cached", "Backend Intern", "Acme", "Remote", "internship", "https://jobs.example/1", "Build APIs", None, "2026-10-09")
    client.app.state.job_repository.upsert_many([cached])

    class BrokenSource:
        name = "broken fixture"

        def fetch(self, query):
            raise AttributeError("bad top-level JSON shape")

    client.app.state.job_sources = [BrokenSource()]
    response = client.post("/api/jobs/refresh", json={})

    assert response.status_code == 200
    assert response.json()["sources"][0]["error"]
    assert len(client.get("/api/jobs?q=intern").json()) == 1


def test_search_results_explain_local_technology_role_match(client):
    listing = JobListing("fixture", "intern", "Software Engineering Intern", "Acme", "Remote", "internship", "https://jobs.example/intern", "Build Python services", None, "2026-10-09")
    client.app.state.job_repository.upsert_many([listing])

    result = client.get("/api/jobs?q=software").json()[0]

    assert result["technology_score"] == 100
    assert result["technology_reasons"] == ["Technology role: software", "Internship or early-career signal"]


def test_manual_recheck_exposes_persisted_evidence_without_application_or_planner_work(client):
    from careeros.jobs.verification import VerificationResult
    job = client.post('/api/jobs/manual', json={'title': 'Software Intern', 'company': 'Acme', 'location': 'Seattle, WA', 'url': 'https://jobs.example/one'}).json()
    repository = client.app.state.job_repository
    failure = VerificationResult('held', 'HTTP 503', 'https://employer.example/one', '2026-10-13T12:00:00+00:00', outcome='transient_error', checked_url=job['url'])
    with repository.db.connect() as conn:
        repository.save_verification(conn, job['id'], failure, attempts=3)
    success = VerificationResult('verified', 'Primary posting', 'https://employer.example/one', '2026-10-13T13:00:00+00:00', 'Build APIs', 'body-hash',
                                 checked_url=job['url'], evidence_summary='Primary JSON-LD', posting_evidence={'title': 'Software Intern'})
    client.app.state.job_discovery_service.verifier = _FixedVerifier(success)
    first = client.post(f"/api/jobs/{job['id']}/verify").json()
    second = client.post(f"/api/jobs/{job['id']}/verify").json()
    fetched = client.get('/api/jobs').json()[0]
    assert first['employer_verification'] == second['employer_verification'] == fetched['employer_verification']
    record = first['employer_verification']
    assert record['outcome'] == 'verified'
    assert record['checked_url'] == 'https://jobs.example/one'
    assert record['final_url'] == 'https://employer.example/one'
    assert record['checked_at'] == '2026-10-13T13:00:00+00:00'
    assert record['retry_eligible'] is False
    assert record['can_recheck'] is True
    assert record['evidence_summary'] == 'Primary JSON-LD'
    assert client.app.state.application_service.list() == []
    assert client.app.state.fake_planner.calls == []
    with repository.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM job_verifications').fetchone()[0] == 1


def test_manual_recheck_timeout_remains_held_and_exposes_provenance(client):
    listing = JobListing('fixture', 'one', 'Software Intern', 'Acme', 'Seattle, WA', 'internship', 'https://jobs.example/one', 'Build APIs', None, 'source-time',
                         source_url='https://feed.example/one', application_url='https://apply.example/one', requisition_id='REQ-1')
    client.app.state.job_repository.upsert_many([listing])
    job = client.app.state.job_repository.recent()[0]

    class TimeoutVerifier:
        def verify(self, *args):
            raise httpx.ConnectTimeout('timeout')

    client.app.state.job_discovery_service.verifier = TimeoutVerifier()
    response = client.post(f'/api/jobs/{job.id}/verify')
    assert response.status_code == 200
    data = response.json()
    assert (data['source_url'], data['application_url'], data['requisition_id'], data['fetched_at']) == ('https://feed.example/one', 'https://apply.example/one', 'REQ-1', 'source-time')
    assert data['employer_verification']['outcome'] == 'transient_error'
    assert data['employer_verification']['status'] == 'held'
    assert data['employer_verification']['retry_eligible'] is True
    assert client.get('/api/jobs').json()[0]['employer_verification'] == data['employer_verification']


def test_manual_recheck_does_not_reset_exhausted_automatic_retry_budget(client):
    from careeros.jobs.verification import VerificationResult
    job = client.post('/api/jobs/manual', json={'title': 'Software Intern', 'company': 'Acme', 'location': 'Seattle, WA', 'url': 'https://jobs.example/one'}).json()
    failure = VerificationResult('held', 'HTTP 503', None, '2026-10-13T12:00:00+00:00', outcome='transient_error')
    repository = client.app.state.job_repository
    with repository.db.connect() as conn:
        repository.save_verification(conn, job['id'], failure, attempts=3)
    client.app.state.job_discovery_service.verifier = _FixedVerifier(failure)
    checked = client.post(f"/api/jobs/{job['id']}/verify").json()['employer_verification']
    assert checked['status'] == 'held'
    assert checked['outcome'] == 'transient_error'
    assert checked['attempts'] == 3
    assert checked['next_retry_at'] is None
    assert checked['retry_eligible'] is False
    assert checked['can_recheck'] is True
    assert client.app.state.fake_planner.calls == []



def test_job_search_exposes_employer_verification_reason(client):
    listing = {"title": "Software Intern", "company": "Seattle Co", "location": "Seattle, WA", "url": "https://jobs.example/us"}
    job = client.post("/api/jobs/manual", json=listing).json()
    with client.app.state.db.connect() as conn:
        conn.execute(
            "INSERT INTO job_verifications(job_id,status,reason,final_url,checked_at,text,fingerprint) VALUES(?,?,?,?,?,?,?)",
            (job["id"], "held", "Employer page returned HTTP 403", job["url"], "test-time", "", None),
        )

    result = client.get("/api/jobs?us_only=false").json()[0]

    assert result["employer_verification"] == {
        "status": "held", "reason": "Employer page returned HTTP 403", "checked_at": "test-time",
        "outcome": "insufficient_detail", "checked_url": None, "final_url": job["url"],
        "evidence_summary": "", "attempts": 0, "next_retry_at": None, "retry_eligible": False, "can_recheck": True,
    }
