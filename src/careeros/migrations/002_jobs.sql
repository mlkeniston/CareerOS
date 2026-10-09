CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'other',
    original_kind TEXT NOT NULL DEFAULT '',
    remote INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    is_saved INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source, external_id)
);
CREATE INDEX jobs_saved_idx ON jobs(is_saved, fetched_at DESC);
