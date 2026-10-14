ALTER TABLE jobs ADD COLUMN application_url TEXT;
ALTER TABLE jobs ADD COLUMN requisition_id TEXT;

ALTER TABLE job_verifications ADD COLUMN outcome TEXT NOT NULL DEFAULT 'insufficient_detail'
  CHECK(outcome IN ('verified','closed','identity_mismatch','insufficient_detail','access_restricted','not_found','transient_error','unsafe_destination'));
ALTER TABLE job_verifications ADD COLUMN checked_url TEXT;
ALTER TABLE job_verifications ADD COLUMN evidence_summary TEXT NOT NULL DEFAULT '';
ALTER TABLE job_verifications ADD COLUMN posting_evidence_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE job_verifications ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3);
ALTER TABLE job_verifications ADD COLUMN next_retry_at TEXT;
UPDATE job_verifications SET outcome='verified' WHERE status='verified';
