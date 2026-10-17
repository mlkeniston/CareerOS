ALTER TABLE jobs ADD COLUMN location_status TEXT NOT NULL DEFAULT 'unknown'
  CHECK(location_status IN ('us','outside_us','unknown'));
CREATE INDEX jobs_location_status_idx ON jobs(location_status, published_at DESC);
