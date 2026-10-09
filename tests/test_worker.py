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
