CREATE TABLE profiles (
    id INTEGER PRIMARY KEY CHECK(id=1),
    name TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    target_roles_json TEXT NOT NULL DEFAULT '[]',
    preferred_locations_json TEXT NOT NULL DEFAULT '[]',
    skills_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE resumes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    resume_id TEXT NOT NULL REFERENCES resumes(id),
    task_id TEXT REFERENCES tasks(id),
    status TEXT NOT NULL CHECK(status IN ('preparing','needs_review','approved','failed')),
    draft_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX applications_updated_idx ON applications(updated_at DESC);
