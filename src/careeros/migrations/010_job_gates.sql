ALTER TABLE profiles ADD COLUMN eligibility_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE job_verifications (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
    status TEXT NOT NULL CHECK(status IN ('verified', 'held')),
    reason TEXT NOT NULL,
    final_url TEXT,
    checked_at TEXT NOT NULL,
    text TEXT NOT NULL,
    fingerprint TEXT
);

CREATE TABLE job_gate_results (
    job_id TEXT NOT NULL REFERENCES jobs(id),
    name TEXT NOT NULL,
    passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
    reason TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY(job_id, name)
);
