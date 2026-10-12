import json

import pytest

from careeros.jobs.models import JobListing
from careeros.portfolio.service import PortfolioBrief
from careeros.workflows.repository import WorkflowRepository


@pytest.fixture
def workflow_repository(db):
    return WorkflowRepository(db)


@pytest.fixture
def running_task(queue):
    task_id = queue.enqueue("application", {}, "ollama")
    assert queue.claim_next({"application"}).id == task_id
    return task_id


def add_test_handoff(repo, task, idempotency_key, **changes):
    event = {
        "idempotency_key": idempotency_key,
        "task_id": task,
        "object_type": "application",
        "object_id": "application-1",
        "from_worker": "application-prep",
        "to_worker": "resume-analyst",
        "event_type": "draft-submitted",
        "payload": {"from_station_id": "application-team-01", "to_station_id": "resume-team-01", "item_type": "document"},
    }
    event.update(changes)
    with repo.db.connect() as conn:
        return repo.record(conn, **event)


def test_handoff_endpoint_uses_exclusive_cursor(client, workflow_repository, running_task):
    add_test_handoff(workflow_repository, running_task, idempotency_key="first")
    add_test_handoff(workflow_repository, running_task, idempotency_key="second")
    response = client.get("/api/workspace/handoffs?after_id=1")
    assert response.status_code == 200
    assert [event["id"] for event in response.json()["events"]] == [2]
    assert response.json()["latest_id"] == 2


def test_handoff_endpoint_keeps_high_water_mark_and_filters_private_payload(client, workflow_repository, running_task):
    add_test_handoff(
        workflow_repository, running_task, idempotency_key="private",
        payload={
            "from_station_id": "application-team-01", "to_station_id": "resume-team-01",
            "item_type": "document", "resume": "PRIVATE RESUME", "model_prompt": "PRIVATE PROMPT",
            "employer_page": "PRIVATE EMPLOYER PAGE", "profile": "PRIVATE PROFILE",
        },
    )
    snapshot = client.get("/api/workspace").json()
    assert snapshot["handoff_cursor"] == 1
    response = client.get("/api/workspace/handoffs?after_id=0")
    assert response.status_code == 200
    event = response.json()["events"][0]
    assert event["from_station_id"] == "application-team-01"
    assert event["to_station_id"] == "resume-team-01"
    assert event["item_type"] == "document"
    assert event["payload"] == {
        "from_station_id": "application-team-01", "to_station_id": "resume-team-01", "item_type": "document",
    }
    assert "PRIVATE" not in response.text
    empty = client.get("/api/workspace/handoffs?after_id=1").json()
    assert empty == {"events": [], "latest_id": 1}


@pytest.mark.parametrize("query", ["after_id=-1", "limit=0", "limit=101"])
def test_handoff_endpoint_rejects_invalid_cursor_or_limit(client, query):
    assert client.get(f"/api/workspace/handoffs?{query}").status_code == 422


def test_handoff_endpoint_applies_limit_in_id_order(client, workflow_repository, running_task):
    for key in ("first", "second", "third"):
        add_test_handoff(workflow_repository, running_task, idempotency_key=key)
    result = client.get("/api/workspace/handoffs?after_id=0&limit=2").json()
    assert [event["id"] for event in result["events"]] == [1, 2]
    assert result["latest_id"] == 3


def test_snapshot_maps_queue_states_and_sanitizes_private_content(client, monkeypatch):
    app = client.app
    monkeypatch.setattr(app.state.gateway.planners["ollama"], "health", lambda: "ready", raising=False)
    app.state.settings.openai_api_key = "sk-workspace-secret"
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES('planner_provider','openai')")

    job = app.state.job_repository.add_manual(JobListing(
        "fixture", "private", "Software Intern", "Acme", "Remote", "internship",
        "https://jobs.example/private", "PRIVATE JOB DESCRIPTION", None, "2026-10-09",
    ))
    resume = app.state.resume_repository.create("Private", "PRIVATE RESUME TEXT")
    app.state.profile_repository.update("", "PRIVATE PROFILE SUMMARY", [], [], [])

    running_app, running_task = app.state.application_service.create(job.id, resume.id, "ollama")
    review_app, review_task = app.state.application_service.create(job.id, resume.id, "ollama")
    approved_app, approved_task = app.state.application_service.create(job.id, resume.id, "ollama")
    queue = app.state.queue
    assert queue.claim_next({"application"}).id == running_task
    assert queue.claim_next({"application"}).id == review_task
    assert queue.claim_next({"application"}).id == approved_task
    queue.finish(review_task, {"draft": "PRIVATE DRAFT CONTENT"}, "needs_review")
    queue.finish(approved_task, {"draft": "PRIVATE APPROVED CONTENT"}, "needs_review")
    with app.state.db.connect() as conn:
        conn.execute("UPDATE tasks SET status='running',updated_at='2026-10-09T12:00:00+00:00' WHERE id=?", (running_task,))
        conn.execute("UPDATE applications SET status='needs_review',draft_json=? WHERE id=?", (json.dumps({"cover_letter": "PRIVATE DRAFT CONTENT"}), review_app.id))
        conn.execute("UPDATE applications SET status='approved' WHERE id=?", (approved_app.id,))

    review_portfolio_task, review_proposal_id = app.state.portfolio_service.create(
        PortfolioBrief("reviewed", "Private proposal", "PRIVATE PROPOSAL BRIEF"), "ollama"
    )
    applied_portfolio_task, applied_proposal_id = app.state.portfolio_service.create(
        PortfolioBrief("shipped", "Private applied proposal", "PRIVATE APPLIED BRIEF"), "ollama"
    )
    assert queue.claim_next({"portfolio"}).id == review_portfolio_task
    assert queue.claim_next({"portfolio"}).id == applied_portfolio_task
    queue.finish(review_portfolio_task, {"files": "PRIVATE PROPOSAL FILE"}, "needs_review")
    queue.finish(applied_portfolio_task, {"files": "PRIVATE APPLIED FILE"}, "needs_review")
    with app.state.db.connect() as conn:
        conn.execute("UPDATE portfolio_proposals SET status='needs_review',summary=? WHERE id=?", ("PRIVATE PROPOSAL SUMMARY", review_proposal_id))
        conn.execute("UPDATE portfolio_proposals SET status='applied' WHERE id=?", (applied_proposal_id,))

    discovery_failed = queue.enqueue("job_discovery", {}, "ollama")
    assert queue.claim_next({"job_discovery"}).id == discovery_failed
    queue.fail(discovery_failed, "PRIVATE TASK ERROR")
    discovery_done = queue.enqueue("job_discovery", {}, "ollama")
    assert queue.claim_next({"job_discovery"}).id == discovery_done
    queue.finish(discovery_done, {"jobs_found": 18, "private": "PRIVATE TASK RESULT"})
    discovery_waiting = queue.enqueue("job_discovery", {"private": "PRIVATE TASK PAYLOAD"}, "ollama")
    outreach_draft, outreach_task = app.state.outreach_service.create_automatic(job.id, resume.id, "private-outreach")
    assert queue.claim_next({"outreach"}).id == outreach_task
    queue.finish(outreach_task, {"outreach_id": outreach_draft.id}, "needs_review")
    with app.state.db.connect() as conn:
        conn.execute(
            "UPDATE outreach_drafts SET status='needs_review',draft_json=? WHERE id=?",
            (json.dumps({"connection_note": "PRIVATE OUTREACH MESSAGE"}), outreach_draft.id),
        )

    snapshot = client.get("/api/workspace").json()
    workers = {worker["id"]: worker for worker in snapshot["workers"]}

    assert [workers[key]["department"] for key in ("job-hunter", "resume-analyst", "application-prep", "portfolio-engineer", "linkedin-outreach", "director")] == [
        "Job Hunters", "Resume Team", "Application Team", "Engineering Team", "LinkedIn Outreach", "Dispatch"
    ]
    assert workers["job-hunter"]["status"] == "waiting"
    assert workers["job-hunter"]["task_id"] == discovery_waiting
    assert workers["application-prep"]["status"] == "working"
    assert workers["application-prep"]["task_id"] == running_task
    assert workers["application-prep"]["since"] == "2026-10-09T12:00:00+00:00"
    assert workers["portfolio-engineer"]["status"] == "needs_review"
    assert "since" not in workers["portfolio-engineer"]
    assert workers["linkedin-outreach"]["status"] == "needs_review"
    assert workers["linkedin-outreach"]["model"] == "qwen3.5:2b-q4_K_M"
    assert workers["linkedin-outreach"]["model_status"] == "ready"
    assert workers["linkedin-outreach"]["task_id"] == outreach_task
    assert "LinkedIn draft" in workers["linkedin-outreach"]["task_label"]
    assert "target roles" in workers["resume-analyst"]["task_label"].lower()
    assert workers["director"]["status"] != "working"
    assert sum(worker["status"] == "working" for worker in snapshot["workers"]) == 1
    assert snapshot["counts"] == {
        "jobs_found": 1,
        "jobs_matched": 1,
        "tasks_shipped": 2,
        "drafts_to_review": 1,
        "proposals_to_review": 1,
        "outreach_to_review": 1,
    }
    assert len(snapshot["activity"]) <= 10
    assert any(item["label"] == "Indexed 18 roles" for item in snapshot["activity"])
    assert snapshot["model"]["selected_provider"] == "openai"
    assert snapshot["model"]["autopilot_provider"] == "ollama"
    assert snapshot["model"]["state"] == "ready"
    serialized = json.dumps(snapshot)
    for private in (
        "PRIVATE JOB DESCRIPTION", "PRIVATE RESUME TEXT", "PRIVATE PROFILE SUMMARY",
        "PRIVATE DRAFT CONTENT", "PRIVATE APPROVED CONTENT", "PRIVATE PROPOSAL BRIEF",
        "PRIVATE PROPOSAL FILE", "PRIVATE PROPOSAL SUMMARY", "PRIVATE TASK PAYLOAD",
        "PRIVATE TASK ERROR", "PRIVATE TASK RESULT", "PRIVATE OUTREACH MESSAGE", "sk-workspace-secret",
    ):
        assert private not in serialized


def test_snapshot_explains_missing_resume_without_claiming_working(client, monkeypatch):
    monkeypatch.setattr(client.app.state.gateway.planners["ollama"], "health", lambda: "offline", raising=False)

    snapshot = client.get("/api/workspace").json()
    workers = {worker["id"]: worker for worker in snapshot["workers"]}

    assert workers["resume-analyst"]["status"] == "waiting"
    assert "resume" in workers["resume-analyst"]["task_label"].lower()
    assert workers["application-prep"]["status"] == "waiting"
    assert workers["application-prep"]["task_label"] == "Add a resume to enable draft preparation"
    assert workers["application-prep"].get("since") is None
    assert snapshot["model"]["state"] == "offline"


def test_outreach_worker_shows_model_install_state(client, fake_planner):
    fake_planner.health_state = "model_missing"
    client.app.state.settings.outreach_model = "qwen3.5:4b-q4_K_M"

    worker = next(
        item for item in client.get("/api/workspace").json()["workers"]
        if item["id"] == "linkedin-outreach"
    )

    assert worker["model"] == "qwen3.5:4b-q4_K_M"
    assert worker["model_status"] == "model_missing"
    assert "ollama pull qwen3.5:4b-q4_k_m" in worker["task_label"].casefold()
