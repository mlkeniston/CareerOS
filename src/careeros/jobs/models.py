from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


VALID_KINDS = {"internship", "entry-level", "full-time", "contract", "other"}


@dataclass(slots=True)
class JobQuery:
    text: str = ""
    location: str = ""
    kind: str = ""
    remote_only: bool = False
    limit: int = 100

    def __post_init__(self):
        if not 1 <= self.limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        self.text = self.text.strip()[:200]
        self.location = self.location.strip()[:100]
        self.kind = self.kind.strip().lower()[:40]


@dataclass(slots=True)
class JobListing:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    kind: str
    url: str
    description: str
    published_at: str | None
    fetched_at: str
    remote: bool = False
    id: str | None = None
    original_kind: str = ""
    is_saved: bool = False
    source_url: str | None = None
    employer_url: str | None = None
    source_age: str | None = None

    def __post_init__(self):
        for name in ("source", "external_id", "title", "company"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
            setattr(self, name, value.strip()[:240])
        self.title = self.title[:240]
        self.company = self.company[:240]
        self.location = (self.location or "")[:240].strip()
        self.description = (self.description or "")[:100000]
        parsed = urlsplit(self.url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("listing URL must use http or https")
        kind = (self.kind or "other").strip().lower()
        self.kind = kind if kind in VALID_KINDS else "other"
        self.original_kind = (self.original_kind or "")[:80]


@dataclass(slots=True)
class SourceResult:
    jobs: list[JobListing]
    warnings: list[str]
