"""Import public SpeedyApply index rows as unverified job leads."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from careeros.jobs.arbeitnow import normalize_kind
from careeros.jobs.models import JobListing, JobQuery, SourceResult
from careeros.jobs.sources import matches_query


FILES = ("README.md", "NEW_GRAD_USA.md", "INTERN_INTL.md", "NEW_GRAD_INTL.md")
MAX_ROWS = 2000
MAX_INPUT = 2_000_000
MAX_CELL = 500
MAX_WARNINGS = 5


class _Cell(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append(" ")
        if tag == "a" and self.href is None:
            self.href = next((value for key, value in attrs if key == "href" and value), None)

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @property
    def text(self) -> str:
        return " ".join("".join(self.parts).split())[:MAX_CELL]


def _split_row(line: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        return []
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line[1:-1]:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def _http_url(value: str | None) -> bool:
    try:
        parsed = urlsplit(value or "")
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _has_empty_table(markdown: str) -> bool:
    lines = markdown[:MAX_INPUT].splitlines()[:MAX_ROWS]
    for header, separator in zip(lines, lines[1:]):
        columns = _split_row(header.strip())
        rules = _split_row(separator.strip())
        if (
            len(columns) == len(rules) == 6
            and [cell.casefold() for cell in columns] == ["company", "position", "location", "salary", "apply", "age"]
            and all(re.fullmatch(r":?-{3,}:?", cell) for cell in rules)
        ):
            return True
    return False


class SpeedyApplySource:
    name = "speedyapply"

    def __init__(self, client: httpx.Client, repo: str = "speedyapply/2027-SWE-College-Jobs"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("invalid SpeedyApply repository name")
        self.client = client
        self.repo = repo

    @staticmethod
    def parse_markdown(markdown: str, source_url: str) -> tuple[list[JobListing], list[str]]:
        jobs: list[JobListing] = []
        skipped = 0
        stamp = datetime.now(timezone.utc).isoformat()
        for line in markdown[:MAX_INPUT].splitlines()[:MAX_ROWS]:
            cells = _split_row(line.strip())
            if not cells:
                continue
            if cells[0].casefold() == "company" or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            if len(cells) != 6:
                skipped += 1
                continue
            parsed = []
            for cell in cells:
                parser = _Cell()
                parser.feed(cell[:MAX_CELL * 4])
                parsed.append(parser)
            company, title, location, _, application, age = parsed
            if not all((company.text, title.text, location.text)) or not _http_url(application.href):
                skipped += 1
                continue
            employer_url = application.href
            kind_hint = title.text + (" new graduate" if "NEW_GRAD" in source_url else " internship" if "INTERN" in source_url else "")
            try:
                jobs.append(JobListing(
                    source="speedyapply",
                    external_id=hashlib.sha256(employer_url.encode("utf-8")).hexdigest(),
                    title=title.text,
                    company=company.text,
                    location=location.text,
                    kind=normalize_kind(kind_hint),
                    url=employer_url,
                    description="",
                    published_at=None,
                    fetched_at=stamp,
                    remote="remote" in location.text.casefold(),
                    source_url=source_url,
                    employer_url=employer_url,
                    source_age=age.text or None,
                ))
            except ValueError:
                skipped += 1
        warnings = [f"Skipped {skipped} malformed SpeedyApply rows"] if skipped else []
        return jobs, warnings[:MAX_WARNINGS]

    def fetch(self, query: JobQuery) -> SourceResult:
        jobs: list[JobListing] = []
        warnings: list[str] = []
        seen: set[str] = set()
        successes = 0
        for filename in FILES:
            raw_url = f"https://raw.githubusercontent.com/{self.repo}/main/{filename}"
            source_url = f"https://github.com/{self.repo}/blob/main/{filename}"
            try:
                response = self.client.get(raw_url)
                response.raise_for_status()
                parsed, parse_warnings = self.parse_markdown(response.text, source_url)
                if not parsed and not _has_empty_table(response.text):
                    raise ValueError("SpeedyApply file has no expected table")
            except (httpx.HTTPError, ValueError):
                warnings.append(f"{filename}: feed unavailable or malformed")
                continue
            successes += 1
            warnings.extend(f"{filename}: {warning}" for warning in parse_warnings)
            for job in parsed:
                if len(jobs) < query.limit and job.external_id not in seen and matches_query(job, query):
                    seen.add(job.external_id)
                    jobs.append(job)
        if successes == 0:
            raise ValueError("SpeedyApply files unavailable or malformed")
        return SourceResult(jobs, warnings[:MAX_WARNINGS])
