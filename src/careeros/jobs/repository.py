from __future__ import annotations

import sqlite3
import re
import uuid
from dataclasses import asdict

from careeros.db import Database
from careeros.jobs.models import JobListing, JobQuery
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
                conn.execute("""INSERT INTO jobs(id,source,external_id,title,company,location,kind,original_kind,remote,url,description,published_at,fetched_at,is_saved)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET
                    title=excluded.title,company=excluded.company,location=excluded.location,kind=excluded.kind,original_kind=excluded.original_kind,
                    remote=excluded.remote,url=excluded.url,description=excluded.description,published_at=excluded.published_at,fetched_at=excluded.fetched_at""",
                    (values["id"] or str(uuid.uuid4()), values["source"], values["external_id"], values["title"], values["company"], values["location"], values["kind"], values["original_kind"], int(values["remote"]), values["url"], values["description"], values["published_at"], stamp, int(values["is_saved"])))
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
            where.append("location LIKE ? ESCAPE '\\'")
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
        params.append(query.limit)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT jobs.* FROM jobs" + joins + clause + " ORDER BY coalesce(published_at,'') DESC, company, title LIMIT ?", params).fetchall()
        return [_job(row) for row in rows]


def _job(row: sqlite3.Row) -> JobListing:
    return JobListing(row["source"], row["external_id"], row["title"], row["company"], row["location"], row["kind"], row["url"], row["description"], row["published_at"], row["fetched_at"], bool(row["remote"]), row["id"], row["original_kind"], bool(row["is_saved"]))
