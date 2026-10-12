from datetime import datetime, timezone

import pytest

from careeros.queue import InvalidTaskTransition, PaidUseConfirmationRequired, TaskQueue
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


def test_retry_is_bounded_and_cloud_is_never_requeued(queue):
    local_id = queue.enqueue("application", {}, "ollama")
    first = queue.claim_next({"application"})
    assert first.id == local_id
    assert first.attempt_count == 1
    assert queue.retry(local_id, "Ollama offline", delay_seconds=300, max_attempts=3)
    pending = queue.get(local_id)
    assert pending.status == "queued"
    assert pending.attempt_count == 1
    assert datetime.fromisoformat(pending.available_at) > datetime.now(timezone.utc)
    assert queue.claim_next({"application"}) is None

    cloud_id = queue.enqueue("application", {}, "openai", cloud_confirmed=True)
    assert queue.claim_next({"application"}).id == cloud_id
    with pytest.raises(InvalidTaskTransition):
        queue.retry(cloud_id, "request timed out", delay_seconds=1)
    assert queue.get(cloud_id).status == "running"

    for attempt in (2, 3):
        with queue.db.connect() as conn:
            conn.execute("UPDATE tasks SET available_at='2000-01-01T00:00:00+00:00' WHERE id=?", (local_id,))
        claimed = queue.claim_next({"application"})
        assert claimed.id == local_id
        assert claimed.attempt_count == attempt
        assert queue.retry(local_id, "Ollama offline", delay_seconds=1, max_attempts=3) is (attempt < 3)
        if attempt == 2:
            assert queue.get(local_id).status == "queued"
            assert datetime.fromisoformat(queue.get(local_id).available_at) > datetime.now(timezone.utc)
    assert queue.get(local_id).status == "running"


@pytest.mark.parametrize("delay,limit", [(0, 3), (3601, 3), (1, 0)])
def test_retry_rejects_invalid_bounds(queue, delay, limit):
    task_id = queue.enqueue("application", {}, "ollama")
    queue.claim_next({"application"})
    with pytest.raises(ValueError):
        queue.retry(task_id, "offline", delay_seconds=delay, max_attempts=limit)


def test_retry_requires_running_task_and_sanitizes_diagnostic(queue):
    task_id = queue.enqueue("application", {}, "ollama")
    with pytest.raises(InvalidTaskTransition):
        queue.retry(task_id, "offline", delay_seconds=1)
    queue.claim_next({"application"})
    assert queue.retry(task_id, "offline\n" + "x" * 300, delay_seconds=1)
    assert queue.get(task_id).error == "offline " + "x" * 232
