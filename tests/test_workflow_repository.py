import pytest

from careeros.queue import TaskQueue
from careeros.workflows.repository import WorkflowRepository


@pytest.fixture
def running_task(db):
    queue = TaskQueue(db)
    task_id = queue.enqueue("job_discovery", {}, "ollama")
    task = queue.claim_next({"job_discovery"})
    assert task is not None and task.id == task_id
    return task


def test_handoffs_are_idempotent_and_ordered(db, running_task):
    repo = WorkflowRepository(db)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        first = repo.record(
            conn, idempotency_key="application:a:manager:1", task_id=running_task.id,
            object_type="application", object_id="a", from_worker="resume-analyst",
            to_worker="hiring-manager", event_type="draft-submitted", payload={"item": "resume"},
        )
        duplicate = repo.record(
            conn, idempotency_key="application:a:manager:1", task_id=running_task.id,
            object_type="application", object_id="a", from_worker="resume-analyst",
            to_worker="hiring-manager", event_type="draft-submitted", payload={"item": "resume"},
        )
        conn.commit()
    assert duplicate.id == first.id
    assert repo.after(0) == [first]
    assert repo.latest_id() == first.id

    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            repo.record(
                conn, idempotency_key="application:a:manager:2", task_id=running_task.id,
                object_type="application", object_id="a", from_worker="resume-analyst",
                to_worker="hiring-manager", event_type="draft-submitted", payload={"item": "resume"},
            )
            raise RuntimeError("rollback test")
    assert repo.latest_id() == first.id

    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        second = repo.record(
            conn, idempotency_key="application:a:manager:3", task_id=running_task.id,
            object_type="application", object_id="a", from_worker="hiring-manager",
            to_worker="application-writer", event_type="approved", payload={},
        )
        conn.commit()
    assert second.id > first.id
    assert repo.after(first.id) == [second]


def test_handoffs_reject_key_reuse_with_different_fields(db, running_task):
    repo = WorkflowRepository(db)
    values = dict(
        idempotency_key="application:a:manager:1", task_id=running_task.id,
        object_type="application", object_id="a", from_worker="resume-analyst",
        to_worker="hiring-manager", event_type="draft-submitted", payload={"item": "resume"},
    )
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        repo.record(conn, **values)
        conn.commit()
    with db.connect() as conn, pytest.raises(ValueError, match="idempotency"):
        conn.execute("BEGIN IMMEDIATE")
        repo.record(conn, **{**values, "object_id": "different"})


def test_handoffs_reject_invalid_or_oversized_payloads(db, running_task):
    repo = WorkflowRepository(db)
    base = dict(
        task_id=running_task.id, object_type="application", object_id="a",
        from_worker="resume-analyst", to_worker="hiring-manager",
        event_type="draft-submitted",
    )
    with db.connect() as conn, pytest.raises(ValueError, match="JSON"):
        repo.record(conn, idempotency_key="bad-json", payload={"bad": object()}, **base)
    with db.connect() as conn, pytest.raises(ValueError, match="16 KB"):
        repo.record(conn, idempotency_key="too-large", payload={"data": "x" * 17000}, **base)


def test_after_and_latest_id_handle_empty_ledger(db):
    repo = WorkflowRepository(db)
    assert repo.after(0) == []
    assert repo.latest_id() == 0
