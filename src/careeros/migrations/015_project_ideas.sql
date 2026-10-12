CREATE TABLE project_ideas (
  id TEXT PRIMARY KEY CHECK (length(id) = 64),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
  summary TEXT NOT NULL CHECK (length(summary) <= 2000),
  skills_json TEXT NOT NULL,
  source_urls_json TEXT NOT NULL CHECK (source_urls_json <> '[]'),
  published_at TEXT,
  retrieved_at TEXT NOT NULL,
  seen_count INTEGER NOT NULL DEFAULT 1 CHECK (seen_count >= 1)
);

CREATE INDEX project_ideas_retrieved_at_idx ON project_ideas(retrieved_at DESC);
