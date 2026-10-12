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


def test_upgrade_from_006_preserves_tasks(tmp_path):
    import json
    import sqlite3
    from pathlib import Path

    from careeros.db import Database

    path = tmp_path / "legacy.sqlite3"
    migration_dir = Path(__file__).parents[1] / "src" / "careeros" / "migrations"
    legacy_migrations = sorted(migration_dir.glob("00[1-6]_*.sql"))
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        for migration in legacy_migrations:
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (migration.name,))
        conn.execute(
            "INSERT INTO tasks(id,kind,payload_json,provider,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("queued-legacy", "job_discovery", json.dumps({"query": "remote"}), "ollama", "queued", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO tasks(id,kind,payload_json,provider,status,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("completed-legacy", "application_draft", json.dumps({"job_id": "job-1"}), "ollama", "completed", json.dumps({"draft": "ready"}), "2026-01-01T01:00:00+00:00", "2026-01-01T02:00:00+00:00"),
        )

    db = Database(path)
    db.initialize()
    db.initialize()

    queue = TaskQueue(db)
    queued = queue.get("queued-legacy")
    completed = queue.get("completed-legacy")
    assert queued is not None
    assert (queued.status, queued.payload, queued.provider) == ("queued", {"query": "remote"}, "ollama")
    assert completed is not None
    assert (completed.status, completed.result) == ("completed", {"draft": "ready"})
    assert completed.attempt_count == 0
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='007_workflow_handoffs.sql'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='008_task_retries.sql'").fetchone()[0] == 1
