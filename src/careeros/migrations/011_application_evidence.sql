ALTER TABLE applications ADD COLUMN snapshot_json TEXT;
ALTER TABLE applications ADD COLUMN snapshot_hash TEXT;
ALTER TABLE applications ADD COLUMN provider TEXT;
ALTER TABLE applications ADD COLUMN model TEXT;
ALTER TABLE applications ADD COLUMN draft_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE applications ADD COLUMN clearance_stale INTEGER NOT NULL DEFAULT 1 CHECK(clearance_stale IN (0,1));
ALTER TABLE applications ADD COLUMN revision_task_id TEXT REFERENCES tasks(id);

CREATE TRIGGER applications_snapshot_immutable BEFORE UPDATE OF snapshot_json,snapshot_hash ON applications
WHEN OLD.snapshot_json IS NOT NULL AND
    (NEW.snapshot_json IS NOT OLD.snapshot_json OR NEW.snapshot_hash IS NOT OLD.snapshot_hash)
BEGIN
    SELECT RAISE(ABORT, 'Application snapshot is immutable');
END;

CREATE TABLE application_claim_evidence (
    application_id TEXT NOT NULL REFERENCES applications(id),
    claim_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    quote_anchors_json TEXT NOT NULL,
    PRIMARY KEY(application_id,claim_id,evidence_id)
);
