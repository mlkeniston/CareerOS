from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from careeros.db import Database


class PaidUseConfirmationRequired(ValueError):
    pass


class InvalidTaskTransition(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Task:
    id: str
    kind: str
    payload: dict[str, Any]
    provider: str
    cloud_confirmed: bool
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: str | None = None
    updated_at: str | None = None


class TaskQueue:
    def __init__(self, db: Database):
        self.db = db

    def enqueue(self, kind: str, payload: dict[str, Any], provider: str, cloud_confirmed: bool = False) -> str:
        with self.db.connect() as conn:
            return self.enqueue_in_transaction(conn, kind, payload, provider, cloud_confirmed)

    def enqueue_in_transaction(self, conn: sqlite3.Connection, kind: str, payload: dict[str, Any], provider: str, cloud_confirmed: bool = False) -> str:
        """Insert a task into the caller's transaction with its domain record."""
        provider = provider.strip().lower()
        if provider not in {"ollama", "openai"}:
            raise ValueError("Choose Ollama or OpenAI")
        if provider == "openai" and not cloud_confirmed:
            raise PaidUseConfirmationRequired("Confirm paid OpenAI use before creating this task")
        task_id = str(uuid.uuid4())
        stamp = now()
        conn.execute("INSERT INTO tasks(id,kind,payload_json,provider,cloud_confirmed,status,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?)",
                     (task_id, kind, json.dumps(payload), provider, int(cloud_confirmed), stamp, stamp))
        return task_id

    def get(self, task_id: str) -> Task | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _task(row) if row else None

    def list(self, limit: int = 50) -> list[Task]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_task(row) for row in rows]

    def claim_next(self, allowed_kinds: set[str]) -> Task | None:
        if not allowed_kinds:
            return None
        marks = ",".join("?" for _ in allowed_kinds)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(f"SELECT * FROM tasks WHERE status='queued' AND kind IN ({marks}) ORDER BY created_at LIMIT 1", tuple(allowed_kinds)).fetchone()
            if row is None:
                conn.commit()
                return None
            changed = conn.execute("UPDATE tasks SET status='running',updated_at=? WHERE id=? AND status='queued'", (now(), row["id"])).rowcount
            conn.commit()
        return self.get(row["id"]) if changed else None

    def finish(self, task_id: str, result: dict[str, Any], status: str = "completed") -> None:
        with self.db.connect() as conn:
            self.finish_in_transaction(conn, task_id, result, status)

    def finish_in_transaction(self, conn: sqlite3.Connection, task_id: str, result: dict[str, Any], status: str = "completed") -> None:
        if status not in {"needs_review", "completed"}:
            raise ValueError("invalid completion status")
        result_json = json.dumps(result)
        row = conn.execute("SELECT status,result_json,error FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise LookupError("Task not found")
        if row["status"] == status and row["result_json"] == result_json and row["error"] is None:
            return
        if row["status"] != "running":
            raise InvalidTaskTransition(f"Invalid task transition from {row['status']}; expected running")
        changed = conn.execute(
            "UPDATE tasks SET status=?,result_json=?,error=NULL,updated_at=? WHERE id=? AND status='running'",
            (status, result_json, now(), task_id),
        ).rowcount
        if changed != 1:
            raise InvalidTaskTransition("Task changed state before it could be finished")

    def fail(self, task_id: str, message: str) -> None:
        safe = (message or "Task failed")[:240]
        with self.db.connect() as conn:
            row = conn.execute("SELECT status,error FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise LookupError("Task not found")
            if row["status"] == "failed" and row["error"] == safe:
                return
            if row["status"] != "running":
                raise InvalidTaskTransition(f"Invalid task transition from {row['status']}; expected running")
            changed = conn.execute(
                "UPDATE tasks SET status='failed',error=?,updated_at=? WHERE id=? AND status='running'",
                (safe, now(), task_id),
            ).rowcount
            if changed != 1:
                raise InvalidTaskTransition("Task changed state before it could be failed")

    def recover_after_restart(self) -> int:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            local = conn.execute("UPDATE tasks SET status='queued',updated_at=? WHERE status='running' AND provider='ollama' AND result_json IS NULL", (now(),)).rowcount
            conn.execute("UPDATE tasks SET status='interrupted',error='Cloud request interrupted; start a new task to retry.',updated_at=? WHERE status='running' AND provider='openai' AND result_json IS NULL", (now(),))
            conn.commit()
        return local


def _task(row: Any) -> Task:
    return Task(
        row["id"], row["kind"], json.loads(row["payload_json"]), row["provider"],
        bool(row["cloud_confirmed"]), row["status"],
        json.loads(row["result_json"]) if row["result_json"] else None,
        row["error"], row["created_at"], row["updated_at"],
    )
