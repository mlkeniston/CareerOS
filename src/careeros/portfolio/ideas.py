"""Project idea records and their local, durable source cache."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from careeros.db import Database
from careeros.workflows.errors import RetryableTaskError


MAX_SOURCE_URLS = 10
MAX_SKILLS = 50
MAX_SUMMARY_LENGTH = 2_000
MAX_WARNINGS = 20


def canonical_source_url(value: str) -> str:
    """Normalize public citations to HTTPS and remove non-identity URL parts."""
    if not isinstance(value, str) or len(value) > 2_000:
        raise ValueError("Project idea source URL is invalid")
    try:
        parsed = urlsplit(value.strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() not in {"http", "https"} or not hostname or parsed.username or parsed.password:
            raise ValueError("Project idea source URL is invalid")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Project idea source URL is invalid") from exc
    if port not in (None, 80, 443):
        raise ValueError("Project idea source URL is invalid")

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = ""
    if hostname == "news.ycombinator.com" and path == "/item":
        query_values = [part for part in parsed.query.split("&") if part.startswith("id=")]
        if len(query_values) == 1 and re.fullmatch(r"id=\d{1,20}", query_values[0]):
            query = query_values[0]
    netloc = hostname
    return urlunsplit(("https", netloc, path, query, ""))


def stable_idea_id(source_urls: list[str]) -> str:
    """Key a signal by its normalized citation identity so refreshed text updates it."""
    canonical = sorted({canonical_source_url(value) for value in source_urls})
    if not canonical:
        raise ValueError("Project ideas must retain a public source URL")
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ProjectIdea:
    id: str
    title: str
    summary: str
    skills: list[str]
    source_urls: list[str]
    published_at: str | None

    def __post_init__(self) -> None:
        self.title = " ".join((self.title or "").split())[:300]
        self.summary = " ".join((self.summary or "").split())[:MAX_SUMMARY_LENGTH]
        if not self.title:
            raise ValueError("Project idea title is required")
        unique_skills: list[str] = []
        seen_skills: set[str] = set()
        for skill in self.skills[:MAX_SKILLS]:
            if not isinstance(skill, str):
                continue
            normalized = " ".join(skill.split())[:100]
            if normalized and normalized.casefold() not in seen_skills:
                seen_skills.add(normalized.casefold())
                unique_skills.append(normalized)
        self.skills = unique_skills
        urls = [canonical_source_url(url) for url in self.source_urls[:MAX_SOURCE_URLS]]
        self.source_urls = list(dict.fromkeys(urls))
        if not self.source_urls:
            raise ValueError("Project ideas must retain a public source URL")
        if self.published_at is not None:
            self.published_at = str(self.published_at)[:100]


@dataclass(slots=True)
class ProjectIdeaResult:
    items: list[ProjectIdea] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.warnings = list(dict.fromkeys(str(warning)[:300] for warning in self.warnings if warning))[:MAX_WARNINGS]


class ProjectIdeaSource(Protocol):
    name: str

    def fetch(self, skills: list[str], limit: int = 20) -> ProjectIdeaResult: ...


class ProjectIdeaRepository:
    """SQLite cache that keeps old ideas while sources are temporarily unavailable."""

    def __init__(self, db: Database):
        self.db = db

    def upsert_many(self, items: list[ProjectIdea]) -> int:
        if not items:
            return 0
        stamp = datetime.now(timezone.utc).isoformat()
        count = 0
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for item in items:
                # Derive persistence identity from citations, never from untrusted source IDs.
                item_id = stable_idea_id(item.source_urls)
                conn.execute(
                    """INSERT INTO project_ideas(
                         id, title, summary, skills_json, source_urls_json,
                         published_at, retrieved_at, seen_count
                       ) VALUES(?,?,?,?,?,?,?,1)
                       ON CONFLICT(id) DO UPDATE SET
                         title=excluded.title,
                         summary=excluded.summary,
                         skills_json=excluded.skills_json,
                         source_urls_json=excluded.source_urls_json,
                         published_at=excluded.published_at,
                         retrieved_at=excluded.retrieved_at,
                         seen_count=project_ideas.seen_count + 1""",
                    (
                        item_id,
                        item.title,
                        item.summary,
                        json.dumps(item.skills, ensure_ascii=False),
                        json.dumps(item.source_urls, ensure_ascii=False),
                        item.published_at,
                        stamp,
                    ),
                )
                count += 1
            conn.commit()
        return count

    def get(self, idea_id: str) -> ProjectIdea | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM project_ideas WHERE id=?", (idea_id,)).fetchone()
        return _idea_from_row(row) if row else None

    def list(self, limit: int = 100) -> list[ProjectIdea]:
        limit = max(1, min(int(limit), 1_000))
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM project_ideas ORDER BY retrieved_at DESC, id LIMIT ?",
                (limit,),
            ).fetchall()
        return [_idea_from_row(row) for row in rows]


class ProjectIdeaService:
    """Collect successful public signals and persist them without deleting cached rows."""

    def __init__(self, sources: list[ProjectIdeaSource], repository: ProjectIdeaRepository):
        self.sources = list(sources)
        self.repository = repository

    def collect(self, skills: list[str], limit: int = 20) -> ProjectIdeaResult:
        bounded_limit = _bounded_limit(limit)
        normalized_skills = _normalized_skills(skills)
        if not normalized_skills:
            return ProjectIdeaResult(warnings=["No verified role skills were available for project-idea research."])

        warnings: list[str] = []
        successful_sources = 0
        transient_failures = 0
        by_url: dict[str, ProjectIdea] = {}
        for source in self.sources:
            try:
                result = source.fetch(normalized_skills, bounded_limit)
            except RetryableTaskError:
                transient_failures += 1
                warnings.append(f"{source.name}: public source temporarily unavailable; cached ideas were kept.")
                continue
            successful_sources += 1
            warnings.extend(result.warnings)
            for item in result.items:
                for url in item.source_urls:
                    canonical = canonical_source_url(url)
                    existing = by_url.get(canonical)
                    if existing is None:
                        by_url[canonical] = ProjectIdea(
                            id=stable_idea_id([canonical]),
                            title=item.title,
                            summary=item.summary,
                            skills=item.skills,
                            source_urls=[canonical],
                            published_at=item.published_at,
                        )
                    else:
                        existing.skills = _normalized_skills(existing.skills + item.skills)
                        if not existing.summary and item.summary:
                            existing.summary = item.summary[:MAX_SUMMARY_LENGTH]

        if not successful_sources and transient_failures:
            raise RetryableTaskError("All public project-idea sources are temporarily unavailable; cached ideas were kept.")

        items = list(by_url.values())
        self.repository.upsert_many(items)
        return ProjectIdeaResult(items, warnings)


def _normalized_skills(skills: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for skill in skills[:MAX_SKILLS]:
        if not isinstance(skill, str):
            continue
        normalized = " ".join(skill.split())[:100]
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            result.append(normalized)
    return result


def _bounded_limit(limit: int) -> int:
    try:
        return max(0, min(int(limit), 20))
    except (TypeError, ValueError) as exc:
        raise ValueError("Project idea source limit must be an integer") from exc


def _idea_from_row(row) -> ProjectIdea:
    return ProjectIdea(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        skills=json.loads(row["skills_json"]),
        source_urls=json.loads(row["source_urls_json"]),
        published_at=row["published_at"],
    )
