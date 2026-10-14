from __future__ import annotations

import sqlite3
import re
import uuid
import json
from dataclasses import asdict
from datetime import datetime, timedelta

from careeros.db import Database
from careeros.jobs.location import classify_location, US
from careeros.jobs.models import JobListing, JobQuery
from careeros.jobs.verification import VerificationResult
from careeros.queue import now


class JobRepository:
    def __init__(self, db: Database, fts_enabled: bool | None = None):
        self.db = db
        self.fts_enabled = db.fts_enabled if fts_enabled is None else fts_enabled

    def upsert_many(self, jobs: list[JobListing]) -> int:
        stamp = now()
        with self.db.connect() as conn:
            for job in jobs:
                values = asdict(job)
                conn.execute("""INSERT INTO jobs(id,source,external_id,title,company,location,kind,original_kind,remote,url,description,published_at,fetched_at,is_saved,source_url,employer_url,source_age,application_url,requisition_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET
                    title=excluded.title,company=excluded.company,location=excluded.location,kind=excluded.kind,original_kind=excluded.original_kind,
                    remote=excluded.remote,url=excluded.url,description=excluded.description,published_at=excluded.published_at,fetched_at=excluded.fetched_at,
                    source_url=excluded.source_url,employer_url=excluded.employer_url,source_age=excluded.source_age,
                    application_url=excluded.application_url,requisition_id=excluded.requisition_id""",
                    (values["id"] or str(uuid.uuid4()), values["source"], values["external_id"], values["title"], values["company"], values["location"], values["kind"], values["original_kind"], int(values["remote"]), values["url"], values["description"], values["published_at"], values["fetched_at"] or stamp, int(values["is_saved"]), values["source_url"], values["employer_url"], values["source_age"], values["application_url"], values["requisition_id"]))
        return len(jobs)

    def add_manual(self, job: JobListing) -> JobListing:
        job.source = "manual"
        job.id = str(uuid.uuid4())
        job.external_id = job.id
        self.upsert_many([job])
        return self.get(job.id)

    def get(self, job_id: str) -> JobListing | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job(row) if row else None

    def set_saved(self, job_id: str, saved: bool = True) -> JobListing | None:
        with self.db.connect() as conn:
            conn.execute("UPDATE jobs SET is_saved=? WHERE id=?", (int(saved), job_id))
        return self.get(job_id)

    def search(self, query: JobQuery, saved_only: bool = False) -> list[JobListing]:
        params: list[object] = []
        joins = ""
        where = []
        if query.text:
            terms = re.findall(r"[\w]+", query.text, flags=re.UNICODE)
            if self.fts_enabled and terms:
                joins = " JOIN jobs_fts ON jobs_fts.rowid=jobs.rowid"
                expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
                where.append("jobs_fts MATCH ?")
                params.append(expression)
            else:
                for term in query.text.split():
                    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    where.append("(title LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')")
                    params.extend([f"%{escaped}%"] * 4)
        if query.location:
            where.append("jobs.location LIKE ? ESCAPE '\\'")
            escaped = query.location.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        if query.kind:
            where.append("(kind=? OR lower(original_kind) LIKE ?)")
            params.extend([query.kind, f"%{query.kind}%"])
        if query.remote_only:
            where.append("remote=1")
        if saved_only:
            where.append("is_saved=1")
        clause = " WHERE " + " AND ".join(where) if where else ""
        if not query.us_only:
            params.append(query.limit)
            limit_clause = " LIMIT ?"
        else:
            limit_clause = ""
        with self.db.connect() as conn:
            rows = conn.execute("SELECT jobs.* FROM jobs" + joins + clause + " ORDER BY coalesce(published_at,'') DESC, company, title" + limit_clause, params).fetchall()
        jobs = [_job(row) for row in rows]
        if query.us_only:
            jobs = [job for job in jobs if classify_location(job.location) == US]
        return jobs[:query.limit]

    def recent(self, limit: int = 100) -> list[JobListing]:
        """Return the newest cached listings for matching and office summaries."""
        return self.search(JobQuery(limit=limit))

    def get_verification(self, job_id: str) -> dict | None:
        return self.verifications([job_id]).get(job_id)

    def verifications(self, job_ids: list[str]) -> dict[str, dict]:
        if not job_ids:
            return {}
        marks = ','.join('?' for _ in job_ids)
        with self.db.connect() as conn:
            rows = conn.execute(f'SELECT * FROM job_verifications WHERE job_id IN ({marks})', job_ids).fetchall()
        results = {}
        for row in rows:
            value = dict(row)
            value['posting_evidence'] = json.loads(value.pop('posting_evidence_json'))
            # Old callers insert status without specifying the newer outcome.
            if value['status'] == 'verified':
                value['outcome'] = 'verified'
            results[row['job_id']] = value
        return results

    def save_verification(self, conn: sqlite3.Connection, job_id: str, result: VerificationResult,
                          *, attempts: int | None = None) -> None:
        """Persist evidence inside the caller's gate transaction; repeated writes are idempotent.

        Attempts count automatic checks in the current failure series. Manual checks
        preserve this budget; a successful check clears its retry schedule.
        """
        previous = conn.execute('SELECT attempts FROM job_verifications WHERE job_id=?', (job_id,)).fetchone()
        attempts = attempts if attempts is not None else (previous['attempts'] if previous else 0)
        if not 0 <= attempts <= 3:
            raise ValueError('Automatic verification attempts must be between zero and three')
        retry = None
        if result.outcome == 'transient_error' and attempts < 3:
            try:
                stamp = datetime.fromisoformat(result.checked_at)
                if stamp.tzinfo is not None:
                    retry = (stamp + timedelta(minutes=10 if attempts < 2 else 60)).isoformat(timespec='seconds')
            except ValueError:
                pass  # An unparseable legacy clock cannot authorize a scheduled retry.
        conn.execute('''INSERT INTO job_verifications(job_id,status,reason,final_url,checked_at,text,fingerprint,
                        outcome,checked_url,evidence_summary,posting_evidence_json,attempts,next_retry_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET
                        status=excluded.status,reason=excluded.reason,final_url=excluded.final_url,
                        checked_at=excluded.checked_at,text=excluded.text,fingerprint=excluded.fingerprint,
                        outcome=excluded.outcome,checked_url=excluded.checked_url,evidence_summary=excluded.evidence_summary,
                        posting_evidence_json=excluded.posting_evidence_json,attempts=excluded.attempts,next_retry_at=excluded.next_retry_at''',
                     (job_id, 'verified' if result.outcome == 'verified' else 'held', result.reason, result.final_url,
                      result.checked_at, result.text, result.fingerprint, result.outcome, result.checked_url,
                      result.evidence_summary or '', json.dumps(result.posting_evidence or {}, sort_keys=True), attempts, retry))


def _job(row: sqlite3.Row) -> JobListing:
    return JobListing(row["source"], row["external_id"], row["title"], row["company"], row["location"], row["kind"], row["url"], row["description"], row["published_at"], row["fetched_at"], bool(row["remote"]), row["id"], row["original_kind"], bool(row["is_saved"]), row["source_url"], row["employer_url"], row["source_age"], row["application_url"], row["requisition_id"])
