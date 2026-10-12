import json

from careeros.jobs.models import JobListing, SourceResult
from careeros.planner.protocols import PlannerResult


def test_discovery_creates_one_local_outreach_draft_for_a_matching_role(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.result = PlannerResult(
        json.dumps({
            "connection_note": "Hi, I am interested in the Software Engineer Intern role at Acme.",
            "follow_up_message": "I have built Python APIs and would love to learn more about the internship.",
            "evidence": ["Built Python APIs"],
        }),
        files=[],
    )

    first = _run_discovery(client)

    assert first.result["outreach_queued"] is True
    task = next(task for task in client.app.state.queue.list(20) if task.kind == "outreach")
    assert (task.provider, task.cloud_confirmed, task.status) == ("ollama", False, "queued")

    second = _run_discovery(client)
    assert second.result["outreach_queued"] is False
    assert sum(task.kind == "outreach" for task in client.app.state.queue.list(20)) == 1

    assert client.app.state.worker.run_once()
    drafts = client.get("/api/outreach").json()
    assert len(drafts) == 1
    assert drafts[0]["status"] == "needs_review"
    assert drafts[0]["job_title"] == "Software Engineer Intern"
    assert drafts[0]["draft"]["connection_note"].startswith("Hi, I am interested")
    assert drafts[0]["draft"]["evidence"] == ["Built Python APIs"]


def test_outreach_text_must_be_reviewed_before_export_and_approval_persists(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.result = PlannerResult(
        json.dumps({
            "connection_note": "Hello, I am interested in the role.",
            "follow_up_message": "My resume includes Python API work, and I would love to learn about the team.",
            "evidence": ["Python API work"],
        }),
        files=[],
    )
    _run_discovery(client)
    client.app.state.worker.run_once()
    draft = client.get("/api/outreach").json()[0]

    before_review = client.get(f"/api/outreach/{draft['id']}/export")
    assert before_review.status_code == 409

    edited = {
        "connection_note": "Hello, I am interested in the backend internship.",
        "follow_up_message": "I have worked with Python APIs and would appreciate learning more.",
        "evidence": ["Python API work"],
    }
    saved = client.put(f"/api/outreach/{draft['id']}/draft", json=edited)
    assert saved.status_code == 200
    assert saved.json()["draft"] == edited
    assert client.post(f"/api/outreach/{draft['id']}/approve").json()["status"] == "approved"

    exported = client.get(f"/api/outreach/{draft['id']}/export")
    assert exported.status_code == 200
    assert "Hello, I am interested in the backend internship." in exported.text
    assert "I have worked with Python APIs" in exported.text
    assert "sent" not in exported.text.lower()


def test_connection_note_must_fit_linkedin_basic_invitation_limit(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.result = PlannerResult(
        json.dumps({
            "connection_note": "x" * 201,
            "follow_up_message": "A grounded follow-up message.",
            "evidence": [],
        }),
        files=[],
    )
    _run_discovery(client)

    assert client.app.state.worker.run_once()
    draft = client.get("/api/outreach").json()[0]
    assert draft["status"] == "failed"
    assert draft["draft"] is None

    edited = client.put(
        f"/api/outreach/{draft['id']}/draft",
        json={"connection_note": "x" * 201, "follow_up_message": "Message", "evidence": []},
    )
    assert edited.status_code == 422


def test_outreach_refuses_to_send_resume_to_a_remote_ollama(client, fake_planner):
    _prepare_matching_discovery(client)
    _run_discovery(client)
    fake_planner.base_url = "https://ollama.example.test:11434"

    assert client.app.state.worker.run_once()

    assert fake_planner.calls == []
    draft = client.get("/api/outreach").json()[0]
    assert draft["status"] == "failed"
    task = client.app.state.queue.get(draft["task_id"])
    assert "loopback" in task.error.lower()


def test_remote_ollama_waits_without_repeatedly_queuing_outreach(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.base_url = "https://ollama.example.test:11434"

    first = _run_discovery(client)
    second = _run_discovery(client)

    assert first.result["outreach_queued"] is False
    assert second.result["outreach_queued"] is False
    assert not any(task.kind == "outreach" for task in client.app.state.queue.list(50))
    worker = next(item for item in client.get("/api/workspace").json()["workers"] if item["id"] == "linkedin-outreach")
    assert worker["status"] == "waiting"
    assert "Ollama on this Mac" in worker["task_label"]


def test_missing_outreach_model_waits_without_queuing_tasks(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.health_state = "model_missing"

    first = _run_discovery(client)
    second = _run_discovery(client)

    assert first.result["outreach_queued"] is False
    assert second.result["outreach_queued"] is False
    assert not any(task.kind == "outreach" for task in client.app.state.queue.list(50))
    worker = next(item for item in client.get("/api/workspace").json()["workers"] if item["id"] == "linkedin-outreach")
    assert worker["model_status"] == "model_missing"


def test_outreach_moves_to_the_next_matching_role_after_one_is_already_queued(client):
    _prepare_matching_discovery(client)
    client.app.state.job_discovery_service.sources = [_Source([
        _job("Software Engineer Intern", "Build Python APIs for developer tools."),
        _job("Backend Engineer Intern", "Build Python APIs for internal services."),
    ])]

    first = _run_discovery(client)
    second = _run_discovery(client)
    third = _run_discovery(client)

    assert first.result["outreach_queued"] is True
    assert second.result["outreach_queued"] is True
    assert third.result["outreach_queued"] is False
    drafts = client.app.state.outreach_service.list()
    titles = {client.app.state.job_repository.get(item.job_id).title for item in drafts}
    assert titles == {"Software Engineer Intern", "Backend Engineer Intern"}


def test_malformed_outreach_output_creates_no_partial_draft(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.result = PlannerResult("not json", files=[])
    _run_discovery(client)

    assert client.app.state.worker.run_once()

    drafts = client.get("/api/outreach").json()
    assert len(drafts) == 1
    assert drafts[0]["status"] == "failed"
    assert drafts[0]["draft"] is None


def test_review_draft_and_task_completion_commit_atomically(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.result = PlannerResult(
        json.dumps({
            "connection_note": "Interested in the internship and your team.",
            "follow_up_message": "I have experience building Python APIs.",
            "evidence": ["Python APIs"],
        }),
        files=[],
    )
    _run_discovery(client)
    draft = client.app.state.outreach_service.list()[0]
    task = client.app.state.queue.claim_next({"outreach"})

    client.app.state.outreach_service.handle_task(task)

    saved = client.app.state.outreach_service.get(draft.id)
    saved_task = client.app.state.queue.get(task.id)
    assert saved.status == "needs_review"
    assert saved_task.status == "needs_review"
    assert saved_task.result == {"outreach_id": saved.id}
    assert len(fake_planner.calls) == 1


def test_recovered_prepared_outreach_does_not_call_planner_again(client, fake_planner):
    _prepare_matching_discovery(client)
    fake_planner.result = PlannerResult(
        json.dumps({
            "connection_note": "Interested in the internship and your team.",
            "follow_up_message": "I have experience building Python APIs.",
            "evidence": ["Python APIs"],
        }),
        files=[],
    )
    _run_discovery(client)
    draft = client.app.state.outreach_service.list()[0]
    assert client.app.state.worker.run_once()
    assert client.app.state.outreach_service.get(draft.id).status == "needs_review"
    assert client.app.state.queue.get(draft.task_id).status == "needs_review"
    calls = len(fake_planner.calls)
    with client.app.state.db.connect() as conn:
        conn.execute("UPDATE tasks SET status='running',result_json=NULL WHERE id=?", (draft.task_id,))

    assert client.app.state.queue.recover_after_restart() == 1
    assert client.app.state.worker.run_once()

    assert len(fake_planner.calls) == calls
    assert client.app.state.outreach_service.get(draft.id).status == "needs_review"
    task = client.app.state.queue.get(draft.task_id)
    assert task.status == "needs_review", task


def test_discovery_does_not_queue_outreach_without_profile_and_resume(client):
    app = client.app
    app.state.job_discovery_service.sources = [
        _Source([_job("Software Engineer Intern", "Build Python APIs.")])
    ]
    app.state.job_discovery_service.applications = None
    app.state.job_discovery_service.portfolios = None

    outcome = _run_discovery(client)

    assert outcome.result["outreach_queued"] is False
    assert not any(task.kind == "outreach" for task in app.state.queue.list(20))


def _prepare_matching_discovery(client):
    app = client.app
    app.state.autopilot_state.set_enabled(False)
    app.state.profile_repository.update(
        "Sam",
        "Computer science student looking for backend roles.",
        ["Software Engineer"],
        ["Remote"],
        ["Python", "APIs"],
    )
    app.state.resume_repository.create("Backend", "Built Python APIs for class projects.")
    app.state.job_discovery_service.sources = [
        _Source([_job("Software Engineer Intern", "Build Python APIs for developer tools.")])
    ]
    app.state.job_discovery_service.applications = None
    app.state.job_discovery_service.portfolios = None


def _run_discovery(client):
    app = client.app
    app.state.queue.enqueue("job_discovery", {}, "ollama")
    task = app.state.queue.claim_next({"job_discovery"})
    outcome = app.state.job_discovery_service.handle_task(task)
    app.state.queue.finish(task.id, outcome.result, outcome.status)
    return outcome


def _job(title, description):
    slug = title.lower().replace(" ", "-")
    return JobListing(
        "fixture", slug, title, "Acme", "Remote", "internship",
        f"https://jobs.example/{slug}", description, "2026-10-09",
        "2026-10-09T12:00:00+00:00", remote=True, original_kind="internship",
    )


class _Source:
    name = "fixture-board"

    def __init__(self, jobs):
        self.result = SourceResult(jobs, [])

    def fetch(self, query):
        return self.result
