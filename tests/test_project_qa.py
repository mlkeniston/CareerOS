from __future__ import annotations

import json

from careeros.planner.gateway import ProviderUnavailable
from careeros.planner.protocols import PlannerResult
from careeros.portfolio.ideas import ProjectIdea
from careeros.portfolio.sandbox import SandboxResult


SOURCE = "https://github.com/example/python-observability"


class FakeSandbox:
    def __init__(self, results=None):
        self.results = list(results or [SandboxResult(0, "tests passed", "", 1)])
        self.calls = 0

    def check_available(self):
        return True, "ready"

    def run(self, project_dir, manifest):
        self.calls += 1
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def _install_project_flow(app, sandbox, qa_result=None):
    app.state.sandbox_runner = sandbox
    app.state.project_qa_service.sandbox = sandbox
    planner = app.state.fake_planner
    requests = []
    qa_results = qa_result if isinstance(qa_result, list) else [qa_result]

    def generate(request):
        requests.append(request)
        if "quality assurance reviewer" in request.instruction.lower():
            next_result = qa_results.pop(0) if len(qa_results) > 1 else qa_results[0]
            if isinstance(next_result, Exception):
                raise next_result
            value = next_result or {"verdict": "pass", "findings": []}
        else:
            value = {
                "summary": "A sourced Python observability demo.",
                "manifest": {
                    "runtime": "python", "test_files": ["tests/test_demo.py"],
                    "expected_behavior": ["Reports latency percentiles safely."], "source_urls": [SOURCE],
                },
                "files": [
                    {"path": "demo.py", "content": "def latency(values): return sorted(values)[len(values)//2]"},
                    {"path": "tests/test_demo.py", "content": "import unittest"},
                ],
            }
        return PlannerResult(text=json.dumps(value), files=[])

    planner.generate = generate
    idea = ProjectIdea("idea", "Python observability", "A Python tracing idea", ["Python", "observability"], [SOURCE], "2026-10-10")
    app.state.project_idea_repository.upsert_many([idea])
    task_id, proposal_id = app.state.project_engineering_service.create_from_ideas([idea], ["Python"])
    return proposal_id, requests, task_id


def _run(worker, count):
    for _ in range(count):
        assert worker.run_once(), [(t.kind, t.status, t.error) for t in worker.queue.list()]


def test_sandbox_pass_plus_independent_critique_makes_project_reviewable(client):
    app = client.app
    proposal_id, requests, _ = _install_project_flow(app, FakeSandbox())

    _run(app.state.worker, 2)

    proposal = app.state.portfolio_service.get(proposal_id)
    assert proposal["status"] == "needs_review", [(t.kind, t.status, t.error) for t in app.state.queue.list()]
    assert app.state.project_qa_service.latest(proposal_id).status == "passed"
    qa_worker = next(item for item in client.get("/api/workspace").json()["workers"] if item["id"] == "project-qa")
    assert qa_worker["gender"] == "male"
    assert qa_worker["qa_status"] == "passed"
    assert qa_worker["latest_verdict"] == "pass"
    assert qa_worker["current_item"] == "Python observability"
    assert app.state.portfolio_service.approve(proposal_id)["status"] == "approved"
    assert any("quality assurance reviewer" in request.instruction.lower() for request in requests)


def test_third_failed_project_qa_cycle_sets_quality_hold(app):
    failed = SandboxResult(1, "", "AssertionError: expected 8", 3)
    sandbox = FakeSandbox([failed, failed, failed])
    proposal_id, _, _ = _install_project_flow(app, sandbox)

    _run(app.state.worker, 6)

    proposal = app.state.portfolio_service.get(proposal_id)
    assert proposal["status"] == "quality_hold"
    assert len(app.state.project_qa_service.history(proposal_id)) == 3
    try:
        app.state.portfolio_service.approve(proposal_id)
    except RuntimeError as exc:
        assert "quality hold" in str(exc).lower()
    else:
        raise AssertionError("held project became approvable")
    try:
        app.state.portfolio_service.apply(proposal_id, [])
    except RuntimeError as exc:
        assert "quality hold" in str(exc).lower()
    else:
        raise AssertionError("held project became applicable")


def test_docker_unavailable_holds_project_without_calling_model(app):
    sandbox = FakeSandbox([SandboxResult(None, "", "", 0, available=False, error="Docker missing")])
    proposal_id, requests, _ = _install_project_flow(app, sandbox)

    _run(app.state.worker, 2)

    assert app.state.portfolio_service.get(proposal_id)["status"] == "quality_hold"
    assert app.state.project_qa_service.latest(proposal_id).status == "quality_hold"
    assert not any("quality assurance reviewer" in request.instruction.lower() for request in requests)


def test_local_provider_outage_retries_qa_without_failing_proposal(app):
    sandbox = FakeSandbox()
    proposal_id, _, _ = _install_project_flow(app, sandbox, ProviderUnavailable("Ollama offline"))

    _run(app.state.worker, 2)

    task = next(task for task in app.state.queue.list() if task.kind == "project_qa")
    assert task.kind == "project_qa"
    assert task.status == "queued"
    assert app.state.portfolio_service.get(proposal_id)["status"] == "preparing"
    assert app.state.project_qa_service.history(proposal_id) == []


def test_project_qa_enqueue_is_idempotent_by_proposal_cycle(app):
    proposal_id, _, _ = _install_project_flow(app, FakeSandbox())

    first = app.state.project_qa_service.enqueue(proposal_id, 1)
    second = app.state.project_qa_service.enqueue(proposal_id, 1)

    assert first == second
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE kind='project_qa'").fetchone()[0] == 1


def test_revision_roundtrip_persists_concrete_finding_and_handoffs(app):
    finding = {"issue": "The latency helper fails on empty input.", "severity": "blocking", "file": "demo.py", "evidence": "IndexError"}
    proposal_id, _, _ = _install_project_flow(app, FakeSandbox([SandboxResult(0, "ok", "", 1), SandboxResult(0, "ok", "", 1)]),
                                               [{"verdict": "revise", "findings": [finding]}, {"verdict": "pass", "findings": []}])

    _run(app.state.worker, 4)

    history = app.state.project_qa_service.history(proposal_id)
    assert [item.status for item in history] == ["revise", "passed"]
    assert history[0].critique["findings"][0]["issue"] == finding["issue"]
    with app.state.db.connect() as conn:
        events = conn.execute("SELECT event_type,from_worker,to_worker,payload_json FROM workflow_handoffs ORDER BY id").fetchall()
    assert [(event["event_type"], event["from_worker"], event["to_worker"]) for event in events] == [
        ("project-submitted", "portfolio-engineer", "project-qa"),
        ("project-defect-returned", "project-qa", "portfolio-engineer"),
        ("project-submitted", "portfolio-engineer", "project-qa"),
        ("project-qa-passed", "project-qa", "director"),
    ]


def test_failed_repair_moves_project_to_visible_quality_hold(app):
    finding = {"issue": "The latency helper fails on empty input.", "severity": "blocking", "file": "demo.py", "evidence": "IndexError"}
    proposal_id, _, _ = _install_project_flow(app, FakeSandbox(), {"verdict": "revise", "findings": [finding]})
    planner = app.state.fake_planner
    original_generate = planner.generate
    engineering_calls = 0

    def fail_revision(request):
        nonlocal engineering_calls
        if "quality assurance reviewer" in request.instruction.lower():
            return original_generate(request)
        engineering_calls += 1
        if engineering_calls == 2:
            return PlannerResult(text="not a project bundle", files=[])
        return original_generate(request)

    planner.generate = fail_revision
    _run(app.state.worker, 3)

    proposal = app.state.portfolio_service.get(proposal_id)
    assert proposal["status"] == "quality_hold"
    assert "project revision stopped" in proposal["hold_reason"].lower()
    assert app.state.project_qa_service.latest(proposal_id).status == "quality_hold"


def test_malformed_qa_review_is_persisted_as_a_hold(app):
    proposal_id, _, _ = _install_project_flow(app, FakeSandbox(), "not a review object")

    _run(app.state.worker, 2)

    assert app.state.portfolio_service.get(proposal_id)["status"] == "quality_hold"
    assert "invalid review" in app.state.portfolio_service.get(proposal_id)["hold_reason"].lower()
    assert app.state.project_qa_service.latest(proposal_id).status == "quality_hold"


def test_duplicate_completed_qa_task_does_not_create_another_report(app):
    proposal_id, _, _ = _install_project_flow(app, FakeSandbox())
    _run(app.state.worker, 2)
    task = next(task for task in app.state.queue.list() if task.kind == "project_qa")

    app.state.project_qa_service.run_task(task)

    assert len(app.state.project_qa_service.history(proposal_id)) == 1
