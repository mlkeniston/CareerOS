import io
import json
import zipfile

import httpx

from careeros.autopilot.discovery import JobDiscoveryService
from careeros.jobs.models import JobListing, SourceResult
from careeros.jobs.verification import EmployerPostingVerifier
from careeros.planner.protocols import PlannerResult


class FixtureJobSource:
    name = "fixture"

    def __init__(self):
        self.calls = 0

    def fetch(self, query):
        self.calls += 1
        return SourceResult(
            jobs=[
                JobListing(
                    source="fixture",
                    external_id="good-role",
                    title="Backend Intern",
                    company="Acme",
                    location="Remote - United States",
                    kind="internship",
                    url="https://apply.acme.example/backend",
                    description="Backend internship listing",
                    published_at="2026-10-10",
                    fetched_at="2026-10-10T12:00:00+00:00",
                    remote=True,
                    source_url="https://github.com/speedyapply/2027-SWE-College-Jobs",
                    employer_url="https://jobs.acme.example/backend",
                ),
                JobListing(
                    source="fixture",
                    external_id="closed-role",
                    title="Backend Intern",
                    company="Acme",
                    location="Remote - United States",
                    kind="internship",
                    url="https://apply.acme.example/closed",
                    description="Backend internship listing",
                    published_at="2026-10-10",
                    fetched_at="2026-10-10T12:00:00+00:00",
                    remote=True,
                    source_url="https://github.com/speedyapply/2027-SWE-College-Jobs",
                    employer_url="https://jobs.acme.example/closed",
                ),
            ],
            warnings=[],
        )


def test_hiring_pipeline_discovers_reviews_approves_and_exports_locally(client, fake_planner):
    requests = []

    def employer_page(request):
        requests.append((request.method, request.headers.get("host", request.url.host), request.url.path))
        if request.url.path == "/closed":
            return httpx.Response(404, request=request)
        html = """<html><main><h1>Backend Intern</h1>
        <p class="company-name">Acme</p>
        <p>Build useful backend services with Python and SQL. Work with a small engineering team to design,
        test, document, and improve reliable APIs for customers. Collaborate with product and engineering
        partners on practical software projects and support quality releases.</p></main></html>"""
        return httpx.Response(200, text=html, headers={"content-type": "text/html"}, request=request)

    verifier = EmployerPostingVerifier(
        transport=httpx.MockTransport(employer_page),
        resolver=lambda host, port: ["93.184.216.34"],
    )
    discovery = JobDiscoveryService(
        client.app.state.job_repository,
        [FixtureJobSource()],
        applications=client.app.state.application_service,
        portfolios=None,
        profiles=client.app.state.profile_repository,
        resumes=client.app.state.resume_repository,
        outreach=None,
        verifier=verifier,
    )
    client.app.state.job_discovery_service = discovery
    client.app.state.discovery_worker.register("job_discovery", discovery.handle_task)
    client.app.state.application_service.posting_verifier = verifier

    profile = client.put(
        "/api/profile",
        json={"name": "Sam", "target_roles": ["Backend Intern"], "preferred_locations": ["Remote"]},
    )
    assert profile.status_code == 200
    resume = client.post(
        "/api/resumes",
        json={"name": "Base resume", "text": "Built a Python API."},
    )
    assert resume.status_code == 201

    planner_calls = []
    manager_reviews = 0

    def scripted_planner(request):
        nonlocal manager_reviews
        planner_calls.append(request)
        if request.task.startswith("Hiring Manager reference"):
            manager_reviews += 1
            if manager_reviews == 1:
                value = {
                    "verdict": "revise",
                    "findings": [{
                        "issue": "Make the supported backend work easier to find.",
                        "severity": "blocking",
                        "evidence_ids": ["resume:1"],
                        "revision_instruction": "Keep the Python API evidence and foreground it in the materials.",
                    }],
                }
            else:
                value = {"verdict": "pass", "findings": []}
        else:
            value = {
                "resume_text": "Built a Python API.",
                "cover_letter": "Built a Python API.",
                "answers": {},
                "claims": [{
                    "claim_id": "python-api",
                    "text": "Built a Python API.",
                    "evidence_ids": ["resume:1"],
                    "quote_anchors": ["Built a Python API."],
                }],
                "next_steps": ["Review the application before submitting it yourself."],
            }
        return PlannerResult(text=json.dumps(value), files=[])

    fake_planner.generate = scripted_planner

    try:
        # The scheduler starts the public-feed scan on the first worker turn.
        assert client.app.state.discovery_worker.run_once()
        with client.app.state.db.connect() as conn:
            rows = conn.execute("SELECT id FROM jobs ORDER BY external_id").fetchall()
            good_id = conn.execute("SELECT id FROM jobs WHERE external_id='good-role'").fetchone()[0]
            closed_id = conn.execute("SELECT id FROM jobs WHERE external_id='closed-role'").fetchone()[0]
            good_gate = conn.execute(
                "SELECT passed FROM job_gate_results WHERE job_id=? AND name='verified'", (good_id,)
            ).fetchone()[0]
            closed_gate = conn.execute(
                "SELECT passed FROM job_gate_results WHERE job_id=? AND name='verified'", (closed_id,)
            ).fetchone()[0]
        assert len(rows) == 2
        assert good_gate == 1
        assert closed_gate == 0

        # A later scheduled scan returns the same rows while the first application is pending.
        from datetime import datetime, timedelta, timezone

        later = datetime.now(timezone.utc) + timedelta(hours=6)
        assert client.app.state.autopilot_scheduler.maybe_enqueue_discovery(later)
        assert client.app.state.discovery_worker.run_once()
        with client.app.state.db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1

        for _ in range(6):
            client.app.state.worker.run_once()
            items = client.app.state.application_service.list()
            if items and items[0].status == "needs_review":
                break

        application = client.app.state.application_service.list()[0]
        assert application.status == "needs_review"
        assert client.app.state.hiring_manager_service.history(application.id)[0]["verdict"] == "revise"
        assert client.app.state.hiring_manager_service.history(application.id)[1]["verdict"] == "pass"
        assert manager_reviews == 2

        with client.app.state.db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM tasks WHERE provider='openai'").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM tasks WHERE kind='application' AND cloud_confirmed=1").fetchone()[0] == 0

        assert set(client.app.state.gateway.planners) == {"ollama"}
        assert planner_calls
        assert requests
        assert all(method == "GET" and host == "jobs.acme.example" for method, host, _ in requests)
        assert not any(path.startswith("/apply") for _, _, path in requests)

        approved = client.post(f"/api/applications/{application.id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        exported = client.get(f"/api/applications/{application.id}/export")
        assert exported.status_code == 200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as package:
            assert set(package.namelist()) == {
                "resume.docx",
                "cover-letter.docx",
                "application-answers.md",
                "job-source.json",
            }
            source = json.loads(package.read("job-source.json"))
            assert source["job"]["source_url"].startswith("https://github.com/speedyapply/")
    finally:
        verifier.close()
