CREATE TABLE workflow_handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    from_worker TEXT NOT NULL,
    to_worker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX workflow_handoffs_id_created_at_idx ON workflow_handoffs(id, created_at);
