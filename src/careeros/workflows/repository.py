from __future__ import annotations

import json
import sqlite3
from typing import Any

from careeros.db import Database
from careeros.queue import now
from careeros.workflows.models import HandoffEvent


_MAX_PAYLOAD_BYTES = 16 * 1024
_EVENT_FIELDS = (
    "idempotency_key", "task_id", "object_type", "object_id",
    "from_worker", "to_worker", "event_type",
)


class WorkflowRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        conn: sqlite3.Connection,
        *,
        idempotency_key: str,
        task_id: str,
        object_type: str,
        object_id: str,
        from_worker: str,
        to_worker: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> HandoffEvent:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        try:
            payload_json = json.dumps(payload, allow_nan=False, separators=(",", ":"))
            decoded_payload = json.loads(payload_json)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("payload must be JSON serializable") from exc
        if len(payload_json.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError("payload exceeds 16 KB")

        conn.execute(
            """INSERT INTO workflow_handoffs(
                   idempotency_key, task_id, object_type, object_id, from_worker,
                   to_worker, event_type, payload_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(idempotency_key) DO NOTHING""",
            (
                idempotency_key, task_id, object_type, object_id, from_worker,
                to_worker, event_type, payload_json, now(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM workflow_handoffs WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            raise RuntimeError("workflow handoff insert did not produce a row")
        stored_payload = json.loads(row["payload_json"])
        supplied = (
            idempotency_key, task_id, object_type, object_id, from_worker,
            to_worker, event_type,
        )
        stored = tuple(row[field] for field in _EVENT_FIELDS)
        if stored != supplied or stored_payload != decoded_payload:
            raise ValueError("idempotency key already exists with different event data")
        return _event(row, stored_payload)

    def after(self, event_id: int, limit: int = 50) -> list[HandoffEvent]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_handoffs WHERE id>? ORDER BY id ASC LIMIT ?",
                (event_id, limit),
            ).fetchall()
        return [_event(row, json.loads(row["payload_json"])) for row in rows]

    def latest_id(self) -> int:
        with self.db.connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM workflow_handoffs").fetchone()
        return int(row[0])


def _event(row: sqlite3.Row, payload: dict[str, Any]) -> HandoffEvent:
    return HandoffEvent(
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        task_id=row["task_id"],
        object_type=row["object_type"],
        object_id=row["object_id"],
        from_worker=row["from_worker"],
        to_worker=row["to_worker"],
        event_type=row["event_type"],
        payload=payload,
        created_at=row["created_at"],
    )
