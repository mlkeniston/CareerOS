ALTER TABLE portfolio_proposals ADD COLUMN source_urls_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE portfolio_proposals ADD COLUMN manifest_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE portfolio_proposals ADD COLUMN engineering_fingerprint TEXT;
CREATE UNIQUE INDEX portfolio_engineering_fingerprint_idx
  ON portfolio_proposals(engineering_fingerprint) WHERE engineering_fingerprint IS NOT NULL;
