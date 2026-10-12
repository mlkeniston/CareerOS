-- Rebuild the checked parent and its dependent evidence table together, with
-- foreign keys enabled throughout the migration. Preserve every 011 field.
CREATE TABLE applications_new (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    resume_id TEXT NOT NULL REFERENCES resumes(id),
    task_id TEXT REFERENCES tasks(id),
    status TEXT NOT NULL CHECK(status IN ('preparing','manager_review','needs_review','approved','failed','quality_hold')),
    draft_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    snapshot_json TEXT,
    snapshot_hash TEXT,
    provider TEXT,
    model TEXT,
    draft_version INTEGER NOT NULL DEFAULT 0,
    clearance_stale INTEGER NOT NULL DEFAULT 1 CHECK(clearance_stale IN (0,1)),
    revision_task_id TEXT REFERENCES tasks(id),
    manager_cycle INTEGER NOT NULL DEFAULT 0,
    manager_task_id TEXT REFERENCES tasks(id)
);
INSERT INTO applications_new(id,job_id,resume_id,task_id,status,draft_json,created_at,updated_at,
    snapshot_json,snapshot_hash,provider,model,draft_version,clearance_stale,revision_task_id)
SELECT id,job_id,resume_id,task_id,status,draft_json,created_at,updated_at,
    snapshot_json,snapshot_hash,provider,model,draft_version,clearance_stale,revision_task_id FROM applications;
CREATE TEMP TABLE preserved_application_claim_evidence AS SELECT * FROM application_claim_evidence;
DROP TABLE application_claim_evidence;
DROP TABLE applications;
ALTER TABLE applications_new RENAME TO applications;
CREATE INDEX applications_updated_idx ON applications(updated_at DESC);
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
INSERT INTO application_claim_evidence SELECT * FROM preserved_application_claim_evidence;
DROP TABLE preserved_application_claim_evidence;

CREATE TABLE hiring_reviews (
    application_id TEXT NOT NULL REFERENCES applications(id),
    cycle INTEGER NOT NULL CHECK(cycle > 0),
    verdict TEXT NOT NULL CHECK(verdict IN ('pass','revise')),
    findings_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    draft_version INTEGER NOT NULL,
    PRIMARY KEY(application_id,cycle)
);
