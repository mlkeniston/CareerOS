CREATE TABLE outreach_drafts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    resume_id TEXT NOT NULL REFERENCES resumes(id),
    task_id TEXT REFERENCES tasks(id),
    status TEXT NOT NULL CHECK(status IN ('preparing','needs_review','approved','failed')),
    draft_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX outreach_drafts_updated_idx ON outreach_drafts(updated_at DESC);
