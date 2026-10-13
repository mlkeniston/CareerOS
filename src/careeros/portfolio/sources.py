"""Bounded, unauthenticated adapters for public project-idea sources."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from careeros.portfolio.ideas import (
    MAX_SUMMARY_LENGTH,
    ProjectIdea,
    ProjectIdeaResult,
    ProjectIdeaSource,
    stable_idea_id,
)
from careeros.workflows.errors import RetryableTaskError


MAX_RESULTS = 20
MAX_BODY_BYTES = 2_000_000
MAX_READ_CHUNK_BYTES = 64 * 1024
MAX_ROWS = 100
MAX_WARNINGS = 10
DEFAULT_TIMEOUT = httpx.Timeout(12, connect=4)
USER_AGENT = "CareerOS/0.1 (public project-idea research)"


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_markup(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextOnly()
    try:
        parser.feed(value[:MAX_BODY_BYTES])
        parser.close()
    except (AssertionError, ValueError):
        return " ".join(value.split())[:MAX_SUMMARY_LENGTH]
    return " ".join(" ".join(parser.parts).split())[:MAX_SUMMARY_LENGTH]


def _skill_matches(skills: list[str], *values: str) -> list[str]:
    haystack = " ".join(values).casefold()
    return [
        skill
        for skill in skills
        if re.search(r"(?<!\w)" + re.escape(skill.casefold()) + r"(?!\w)", haystack)
    ]


def _limit(value: int) -> int:
    try:
        return max(0, min(int(value), MAX_RESULTS))
    except (TypeError, ValueError) as exc:
        raise ValueError("Project source limit must be an integer") from exc


def _valid_skills(skills: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for skill in skills[:100]:
        if not isinstance(skill, str):
            continue
        normalized = " ".join(skill.split())[:100]
        if normalized and normalized.casefold() not in seen:
            result.append(normalized)
            seen.add(normalized.casefold())
    return result


def _query_skill(skill: str) -> str:
    # Keep user-derived skill text inside a literal search phrase.
    return " ".join(re.sub(r"[^A-Za-z0-9.+# -]", " ", skill).split())[:100]


def _new_idea(title: str, summary: str, skills: list[str], source_url: str, published_at: str | None) -> ProjectIdea:
    return ProjectIdea(
        id=stable_idea_id([source_url]),
        title=title,
        summary=summary,
        skills=skills,
        source_urls=[source_url],
        published_at=published_at,
    )


class _HTTPProjectSource:
    name = "public"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}, trust_env=False)

    def _get(self, url: str, params: dict | None = None) -> tuple[httpx.Response | None, str | None]:
        try:
            with self.client.stream(
                "GET",
                url,
                params=params,
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                if 500 <= response.status_code <= 599:
                    raise RetryableTaskError(f"{self.name} project-idea source returned a temporary server error.")
                if response.status_code != 200:
                    return None, f"{self.name}: source returned HTTP {response.status_code}."

                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes(chunk_size=MAX_READ_CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_BODY_BYTES:
                        return None, f"{self.name}: response exceeded the size limit."
                    chunks.append(chunk)
                headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
                bounded_response = httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=b"".join(chunks),
                    request=response.request,
                )
        except httpx.TimeoutException as exc:
            raise RetryableTaskError(f"{self.name} project-idea source timed out.") from exc
        except httpx.HTTPError as exc:
            raise RetryableTaskError(f"{self.name} project-idea source request failed temporarily.") from exc
        return bounded_response, None


class GitHubProjectSource(_HTTPProjectSource):
    """Search public repositories with the unauthenticated GitHub REST API."""

    name = "GitHub"
    URL = "https://api.github.com/search/repositories"

    def fetch(self, skills: list[str], limit: int = 20) -> ProjectIdeaResult:
        skills = _valid_skills(skills)
        limit = _limit(limit)
        if not skills or not limit:
            return ProjectIdeaResult()
        query_terms = [f'"{term}"' for term in (_query_skill(skill) for skill in skills[:10]) if term]
        if not query_terms:
            return ProjectIdeaResult(warnings=["GitHub: no searchable role skills were available."])
        response, warning = self._get(
            self.URL,
            {"q": " ".join(query_terms) + " in:name,description,readme", "sort": "updated", "order": "desc", "per_page": limit},
        )
        if warning:
            return ProjectIdeaResult(warnings=[warning])
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            return ProjectIdeaResult(warnings=["GitHub: malformed JSON response."])
        rows = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return ProjectIdeaResult(warnings=["GitHub: malformed repository collection."])

        items: list[ProjectIdea] = []
        warnings = 0
        seen: set[str] = set()
        for row in rows[:MAX_ROWS]:
            if not isinstance(row, dict):
                warnings += 1
                continue
            try:
                title = " ".join(str(row.get("full_name") or row.get("name") or "").split())[:300]
                html_url = str(row.get("html_url") or "")
                parsed = urlsplit(html_url)
                parts = [part for part in parsed.path.strip("/").split("/") if part]
                if (
                    parsed.scheme not in {"http", "https"}
                    or (parsed.hostname or "").lower() != "github.com"
                    or parsed.username
                    or parsed.password
                    or parsed.port not in (None, 80, 443)
                    or len(parts) != 2
                ):
                    raise ValueError("invalid repository URL")
                owner, repository = parts
                repository = repository.removesuffix(".git")
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repository):
                    raise ValueError("invalid repository URL")
                source_url = f"https://github.com/{owner}/{repository}"
                description = strip_markup(row.get("description"))
                language = str(row.get("language") or "")[:100]
                matched = _skill_matches(skills, title, description, language)
                if not title:
                    raise ValueError("missing repository title")
                if source_url in seen:
                    continue
                seen.add(source_url)
                if not matched:
                    continue
                items.append(_new_idea(title, description or title, matched, source_url, row.get("created_at")))
                if len(items) >= limit:
                    break
            except (TypeError, ValueError, UnicodeError):
                warnings += 1
        messages = [f"GitHub: skipped {warnings} malformed repository row(s)."] if warnings else []
        return ProjectIdeaResult(items, messages[:MAX_WARNINGS])


class HackerNewsProjectSource(_HTTPProjectSource):
    """Read the public Firebase API's top story IDs and a capped set of stories."""

    name = "Hacker News"
    TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
    ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

    def fetch(self, skills: list[str], limit: int = 20) -> ProjectIdeaResult:
        skills = _valid_skills(skills)
        limit = _limit(limit)
        if not skills or not limit:
            return ProjectIdeaResult()
        response, warning = self._get(self.TOP_STORIES_URL)
        if warning:
            return ProjectIdeaResult(warnings=[warning])
        try:
            values = response.json()
        except (ValueError, UnicodeError):
            return ProjectIdeaResult(warnings=["Hacker News: malformed story ID response."])
        if not isinstance(values, list):
            return ProjectIdeaResult(warnings=["Hacker News: malformed story ID collection."])

        ids: list[int] = []
        seen_ids: set[int] = set()
        warnings = 0
        for value in values[:MAX_ROWS]:
            if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 10**20 and value not in seen_ids:
                ids.append(value)
                seen_ids.add(value)
            else:
                warnings += 1
            if len(ids) >= limit:
                break

        items: list[ProjectIdea] = []
        seen_urls: set[str] = set()
        for item_id in ids:
            response, warning = self._get(self.ITEM_URL.format(item_id=item_id))
            if warning:
                warnings += 1
                continue
            try:
                story = response.json()
            except (ValueError, UnicodeError):
                warnings += 1
                continue
            if not isinstance(story, dict) or story.get("type") != "story" or story.get("id") != item_id:
                warnings += 1
                continue
            title = " ".join(str(story.get("title") or "").split())[:300]
            summary = strip_markup(story.get("text")) or title
            matched = _skill_matches(skills, title, summary)
            source_url = f"https://news.ycombinator.com/item?id={item_id}"
            if not title or not matched or source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            try:
                raw_time = story.get("time")
                published_at = datetime.fromtimestamp(raw_time, timezone.utc).isoformat() if isinstance(raw_time, int) else None
            except (OverflowError, OSError, ValueError):
                published_at = None
                warnings += 1
            items.append(_new_idea(title, summary, matched, source_url, published_at))
        messages = [f"Hacker News: skipped or malformed {warnings} source record(s)."] if warnings else []
        return ProjectIdeaResult(items[:limit], messages[:MAX_WARNINGS])


class ArxivProjectSource(_HTTPProjectSource):
    """Search arXiv's Atom endpoint for public research related to verified skills."""

    name = "arXiv"
    URL = "https://export.arxiv.org/api/query"
    ATOM = "http://www.w3.org/2005/Atom"

    def fetch(self, skills: list[str], limit: int = 20) -> ProjectIdeaResult:
        skills = _valid_skills(skills)
        limit = _limit(limit)
        if not skills or not limit:
            return ProjectIdeaResult()
        terms = [f'all:"{term}"' for term in (_query_skill(skill) for skill in skills[:10]) if term]
        if not terms:
            return ProjectIdeaResult(warnings=["arXiv: no searchable role skills were available."])
        response, warning = self._get(
            self.URL,
            {"search_query": " OR ".join(terms), "start": 0, "max_results": limit, "sortBy": "relevance", "sortOrder": "descending"},
        )
        if warning:
            return ProjectIdeaResult(warnings=[warning])
        try:
            root = ET.fromstring(response.content)
        except (ET.ParseError, ValueError):
            return ProjectIdeaResult(warnings=["arXiv: malformed Atom response."])
        if root.tag.rsplit("}", 1)[-1] != "feed":
            return ProjectIdeaResult(warnings=["arXiv: malformed Atom feed."])

        items: list[ProjectIdea] = []
        warnings = 0
        seen_urls: set[str] = set()
        entries = root.findall(f"{{{self.ATOM}}}entry")
        for entry in entries[:MAX_ROWS]:
            try:
                raw_url = (entry.findtext(f"{{{self.ATOM}}}id") or "").strip()
                parsed = urlsplit(raw_url)
                if (
                    parsed.scheme not in {"http", "https"}
                    or (parsed.hostname or "").lower() != "arxiv.org"
                    or parsed.username
                    or parsed.password
                    or parsed.port not in (None, 80, 443)
                ):
                    raise ValueError("invalid paper URL")
                match = re.fullmatch(
                    r"/abs/((?:\d{4}\.\d{4,5}|[A-Za-z][A-Za-z0-9._-]*/\d{7}))(?:v[0-9]+)?/?",
                    parsed.path,
                )
                if match is None:
                    raise ValueError("invalid paper identifier")
                source_url = f"https://arxiv.org/abs/{match.group(1)}"
                title = strip_markup(entry.findtext(f"{{{self.ATOM}}}title"))[:300]
                summary = strip_markup(entry.findtext(f"{{{self.ATOM}}}summary"))
                matched = _skill_matches(skills, title, summary)
                if not title or source_url in seen_urls:
                    continue
                seen_urls.add(source_url)
                if not matched:
                    continue
                published_at = (entry.findtext(f"{{{self.ATOM}}}published") or "").strip() or None
                items.append(_new_idea(title, summary or title, matched, source_url, published_at))
                if len(items) >= limit:
                    break
            except (TypeError, ValueError, UnicodeError):
                warnings += 1
        messages = [f"arXiv: skipped {warnings} malformed Atom entr(y/ies)."] if warnings else []
        return ProjectIdeaResult(items, messages[:MAX_WARNINGS])


__all__ = [
    "ArxivProjectSource",
    "GitHubProjectSource",
    "HackerNewsProjectSource",
    "ProjectIdeaSource",
]
