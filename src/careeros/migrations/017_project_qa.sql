CREATE TABLE portfolio_proposals_new (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL CHECK(status IN ('preparing','needs_review','approved','applied','failed','quality_hold')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    files_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_urls_json TEXT NOT NULL DEFAULT '[]',
    manifest_json TEXT NOT NULL DEFAULT '{}',
    engineering_fingerprint TEXT,
    hold_reason TEXT
);
INSERT INTO portfolio_proposals_new(id,project_id,task_id,status,title,summary,files_json,created_at,updated_at,
    source_urls_json,manifest_json,engineering_fingerprint)
SELECT id,project_id,task_id,status,title,summary,files_json,created_at,updated_at,
    source_urls_json,manifest_json,engineering_fingerprint FROM portfolio_proposals;
DROP TABLE portfolio_proposals;
ALTER TABLE portfolio_proposals_new RENAME TO portfolio_proposals;
CREATE INDEX portfolio_updated_idx ON portfolio_proposals(updated_at DESC);
CREATE UNIQUE INDEX portfolio_engineering_fingerprint_idx
  ON portfolio_proposals(engineering_fingerprint) WHERE engineering_fingerprint IS NOT NULL;

CREATE TABLE project_qa_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL REFERENCES portfolio_proposals(id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK(cycle > 0 AND cycle <= 3),
    status TEXT NOT NULL CHECK(status IN ('passed','revise','quality_hold')),
    deterministic_report_json TEXT NOT NULL,
    critique_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(proposal_id,cycle)
);
CREATE INDEX project_qa_proposal_cycle_idx ON project_qa_runs(proposal_id,cycle DESC);

CREATE TABLE project_qa_dispatches (
    proposal_id TEXT NOT NULL REFERENCES portfolio_proposals(id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL CHECK(cycle > 0 AND cycle <= 3),
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
    PRIMARY KEY(proposal_id,cycle)
);
