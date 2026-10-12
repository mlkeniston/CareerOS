import pytest

from careeros.queue import PaidUseConfirmationRequired, TaskQueue
from careeros.worker import TaskOutcome, Worker


def test_persist_and_claim_task_once(db):
    queue = TaskQueue(db)
    task_id = queue.enqueue("sample", {"value": 4}, "ollama")
    assert queue.claim_next({"sample"}).id == task_id
    assert queue.claim_next({"sample"}) is None
    assert queue.get(task_id).status == "running"


def test_restart_requeues_local_and_interrupts_cloud(db):
    queue = TaskQueue(db)
    local = queue.enqueue("sample", {}, "ollama")
    cloud = queue.enqueue("sample", {}, "openai", cloud_confirmed=True)
    queue.claim_next({"sample"})
    queue.claim_next({"sample"})
    queue.recover_after_restart()
    assert queue.get(local).status == "queued"
    assert queue.get(cloud).status == "interrupted"


def test_cloud_task_needs_confirmation(db):
    queue = TaskQueue(db)
    try:
        queue.enqueue("sample", {}, "openai")
    except PaidUseConfirmationRequired:
        pass
    else:
        raise AssertionError("cloud enqueue should require confirmation")


def test_worker_persists_review_result(db):
    queue = TaskQueue(db)
    task_id = queue.enqueue("sample", {}, "ollama")
    worker = Worker(queue, {"sample": lambda task: TaskOutcome("needs_review", {"draft": "ready"})})
    assert worker.run_once()
    assert queue.get(task_id).status == "needs_review"
    assert queue.get(task_id).result == {"draft": "ready"}


def test_task_completion_requires_running_state_and_allows_identical_repeat(db):
    queue = TaskQueue(db)
    task_id = queue.enqueue("sample", {}, "ollama")

    with pytest.raises(RuntimeError, match="running"):
        queue.finish(task_id, {"draft": "ready"}, "needs_review")

    assert queue.claim_next({"sample"}).id == task_id
    queue.finish(task_id, {"draft": "ready"}, "needs_review")
    queue.finish(task_id, {"draft": "ready"}, "needs_review")
    assert queue.get(task_id).result == {"draft": "ready"}

    with pytest.raises(RuntimeError, match="transition"):
        queue.finish(task_id, {"draft": "changed"}, "needs_review")


def test_task_failure_requires_running_state_and_is_idempotent(db):
    queue = TaskQueue(db)
    task_id = queue.enqueue("sample", {}, "ollama")

    with pytest.raises(RuntimeError, match="running"):
        queue.fail(task_id, "offline")

    queue.claim_next({"sample"})
    queue.fail(task_id, "offline")
    queue.fail(task_id, "offline")
    assert queue.get(task_id).status == "failed"
    with pytest.raises(RuntimeError, match="transition"):
        queue.finish(task_id, {}, "completed")
