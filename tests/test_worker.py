from threading import Event, Thread

from careeros.jobs.models import SourceResult
from careeros.queue import TaskQueue
from careeros.worker import TaskOutcome, Worker


def test_worker_runs_queued_work_even_when_before_claim_hook_fails(db, caplog):
    queue = TaskQueue(db)
    task_id = queue.enqueue("job_discovery", {}, "ollama")
    worker = Worker(
        queue,
        {"job_discovery": lambda task: TaskOutcome("completed", {"jobs_found": 1})},
        before_claim=lambda: (_ for _ in ()).throw(RuntimeError("scheduler unavailable")),
    )

    assert worker.run_once() is True
    assert queue.get(task_id).status == "completed"
    assert "before_claim hook failed" in caplog.text


def test_slow_job_discovery_does_not_block_application_worker(client):
    resume = client.post("/api/resumes", json={"name": "Backend", "text": "Python"}).json()
    job = client.post("/api/jobs/manual", json={"title": "Backend Intern", "company": "Acme", "url": "https://jobs.example/1"}).json()
    started = client.post("/api/applications", json={"job_id": job["id"], "resume_id": resume["id"], "provider": "ollama"}).json()
    source_started, release_source = Event(), Event()

    class SlowSource:
        name = "slow fixture"

        def fetch(self, query):
            source_started.set()
            assert release_source.wait(timeout=3)
            return SourceResult([], [])

    client.app.state.job_discovery_service.sources = [SlowSource()]
    client.app.state.queue.enqueue("job_discovery", {}, "ollama")
    discovery_thread = Thread(target=client.app.state.discovery_worker.run_once)
    try:
        discovery_thread.start()
        assert source_started.wait(timeout=1)
        assert client.app.state.worker.run_once() is True
        assert client.app.state.application_service.get(started["id"]).status == "needs_review"
    finally:
        release_source.set()
        if discovery_thread.ident is not None:
            discovery_thread.join(timeout=3)
    assert not discovery_thread.is_alive()
