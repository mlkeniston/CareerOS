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
