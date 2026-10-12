import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from careeros.config import Settings
from careeros.main import create_app
from careeros.planner.protocols import PlannerResult
from careeros.queue import TaskQueue


class FakePlanner:
    def __init__(self):
        self.calls = []
        self.result = None
        self.base_url = "http://127.0.0.1:11434"
        self.health_state = "ready"

    def generate(self, request):
        self.calls.append(request)
        if self.result is not None:
            return self.result
        if "portfolio" in request.task.lower():
            value = {"summary": "A small starter", "files": [{"path": "README.md", "content": "generated"}]}
        else:
            value = {"cover_letter": "Draft", "resume_alignment": ["Python"], "answers": {}, "next_steps": ["Review"]}
        return PlannerResult(text=json.dumps(value), files=[])

    def health(self):
        return self.health_state


@pytest.fixture
def app(tmp_path):
    settings = Settings(data_dir=tmp_path, worker_enabled=False)
    application = create_app(settings)
    fake = FakePlanner()
    application.state.fake_planner = fake
    application.state.gateway.planners["ollama"] = fake
    application.state.outreach_service.planner = fake
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(app):
    return app.state.db


@pytest.fixture
def queue(db):
    return TaskQueue(db)


@pytest.fixture
def fake_planner(app):
    return app.state.fake_planner


@pytest.fixture
def arbeitnow_fixture():
    return {"data": [{"slug": "software-intern", "title": "Software Intern", "company_name": "Acme", "location": "Remote", "url": "https://jobs.example/1", "description": "Build APIs", "created_at": "2026-10-09", "job_types": ["Internship"], "remote": True}]}


@pytest.fixture
def greenhouse_fixture():
    return {"jobs": [{"id": 11, "title": "Backend Intern", "location": {"name": "Remote"}, "absolute_url": "https://jobs.example/2", "content": "Build services", "updated_at": "2026-10-08"}]}


@pytest.fixture
def lever_fixture():
    return [{"id": "22", "text": "Platform Intern", "categories": {"location": "Remote", "commitment": "Internship"}, "hostedUrl": "https://jobs.example/3", "descriptionPlain": "Build tools", "createdAt": 1791417600000}]
