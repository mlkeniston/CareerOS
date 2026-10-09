from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from careeros.db import Database
from careeros.queue import now


@dataclass(slots=True)
class Resume:
    id: str
    name: str
    text: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class CareerProfile:
    name: str = ""
    summary: str = ""
    target_roles: list[str] | None = None
    preferred_locations: list[str] | None = None
    skills: list[str] | None = None


class ProfileRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self) -> CareerProfile:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE id=1").fetchone()
            if row is None:
                conn.execute("INSERT INTO profiles(id,updated_at) VALUES(1,?)", (now(),))
                return CareerProfile(target_roles=[], preferred_locations=[], skills=[])
        return CareerProfile(row["name"], row["summary"], json.loads(row["target_roles_json"]), json.loads(row["preferred_locations_json"]), json.loads(row["skills_json"]))

    def update(self, name: str, summary: str, target_roles: list[str], preferred_locations: list[str], skills: list[str]) -> CareerProfile:
        with self.db.connect() as conn:
            conn.execute("""INSERT INTO profiles(id,name,summary,target_roles_json,preferred_locations_json,skills_json,updated_at) VALUES(1,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,summary=excluded.summary,target_roles_json=excluded.target_roles_json,preferred_locations_json=excluded.preferred_locations_json,skills_json=excluded.skills_json,updated_at=excluded.updated_at""",
                         (name[:100], summary[:2000], json.dumps(target_roles[:20]), json.dumps(preferred_locations[:20]), json.dumps(skills[:20]), now()))
        return self.get()


class ResumeRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str, text: str) -> Resume:
        name, text = _validate_resume(name, text)
        stamp, resume_id = now(), str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute("INSERT INTO resumes(id,name,text,created_at,updated_at) VALUES(?,?,?,?,?)", (resume_id, name, text, stamp, stamp))
        return self.get(resume_id)

    def get(self, resume_id: str) -> Resume | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
        return _resume(row) if row else None

    def list(self) -> list[Resume]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM resumes ORDER BY updated_at DESC").fetchall()
        return [_resume(row) for row in rows]

    def most_recent(self) -> Resume | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM resumes ORDER BY updated_at DESC, rowid DESC LIMIT 1").fetchone()
        return _resume(row) if row else None

    def update(self, resume_id: str, name: str, text: str) -> Resume | None:
        name, text = _validate_resume(name, text)
        with self.db.connect() as conn:
            conn.execute("UPDATE resumes SET name=?,text=?,updated_at=? WHERE id=?", (name, text, now(), resume_id))
        return self.get(resume_id)


def _validate_resume(name: str, text: str) -> tuple[str, str]:
    name = (name or "").strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("Resume name must be 1–80 characters")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 200000 or "\0" in text:
        raise ValueError("Resume text must contain 1–200,000 characters and no NUL bytes")
    return name, text.strip()


def _resume(row: sqlite3.Row) -> Resume:
    return Resume(row["id"], row["name"], row["text"], row["created_at"], row["updated_at"])
