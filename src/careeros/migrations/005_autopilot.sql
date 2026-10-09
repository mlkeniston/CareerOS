CREATE TABLE autopilot_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    last_discovery_queued_at TEXT,
    last_error TEXT
);

CREATE TABLE autopilot_dispatches (
    fingerprint TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    created_at TEXT NOT NULL
);

CREATE INDEX autopilot_dispatches_task_idx ON autopilot_dispatches(task_id);
