CREATE TABLE portfolio_proposals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL CHECK(status IN ('preparing','needs_review','approved','applied','failed')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    files_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX portfolio_updated_idx ON portfolio_proposals(updated_at DESC);
