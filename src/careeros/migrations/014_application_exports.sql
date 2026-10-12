CREATE TABLE application_exports (
  application_id TEXT PRIMARY KEY REFERENCES applications(id) ON DELETE CASCADE,
  draft_version INTEGER NOT NULL,
  snapshot_hash TEXT NOT NULL,
  path TEXT NOT NULL,
  exported_at TEXT NOT NULL
);
ALTER TABLE applications ADD COLUMN rejection_reason TEXT;
