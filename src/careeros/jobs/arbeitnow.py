from datetime import datetime, timezone

import httpx

from careeros.jobs.models import JobListing, JobQuery, SourceResult
from careeros.jobs.sources import matches_query


class ArbeitnowSource:
    name = "arbeitnow"
    URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, client: httpx.Client | None = None, max_pages: int = 3):
        self.client = client or httpx.Client(timeout=httpx.Timeout(12, connect=4), headers={"User-Agent": "CareerOS/0.1"}, trust_env=False)
        self.max_pages = max(1, min(max_pages, 3))

    def fetch(self, query: JobQuery) -> SourceResult:
        rows, warnings, seen = [], 0, set()
        for page in range(1, self.max_pages + 1):
            response = self.client.get(self.URL, params={"page": page})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Arbeitnow returned an invalid response object")
            values = payload.get("data", [])
            if not isinstance(values, list):
                raise ValueError("Arbeitnow returned an invalid listing collection")
            if not values:
                break
            for row in values:
                if not isinstance(row, dict):
                    warnings += 1
                    continue
                try:
                    raw_kind = ", ".join(row.get("job_types", []) or [])
                    kind = normalize_kind(raw_kind)
                    external_id = str(row.get("slug") or row["url"])
                    if external_id in seen:
                        continue
                    seen.add(external_id)
                    created = row.get('created_at')
                    published = datetime.fromtimestamp(created, timezone.utc).isoformat() if isinstance(created, (int, float)) else created if isinstance(created, str) else None
                    job = JobListing("arbeitnow", external_id, row["title"], row.get("company_name") or row.get("company") or "Unknown employer", row.get("location") or "", kind, row["url"], strip_html(row.get("description") or ""), published, datetime.now(timezone.utc).isoformat(), bool(row.get("remote")), original_kind=raw_kind,
                        source_url=f"{self.URL}?page={page}", employer_url=row.get('employer_url'),
                        application_url=row.get('application_url'),
                        requisition_id=str(row['requisition_id']) if row.get('requisition_id') is not None else None)
                    if matches_query(job, query):
                        rows.append(job)
                except (KeyError, TypeError, ValueError, OverflowError, OSError):
                    warnings += 1
        return SourceResult(rows, [f"Skipped {warnings} malformed listing" + ("s" if warnings != 1 else "")] if warnings else [])


def normalize_kind(value: str) -> str:
    text = value.casefold()
    if "intern" in text:
        return "internship"
    if "entry" in text or "junior" in text or "graduate" in text:
        return "entry-level"
    if "contract" in text or "freelance" in text:
        return "contract"
    if "full" in text or "permanent" in text:
        return "full-time"
    return "other"


def strip_html(value: str) -> str:
    import re
    from html import unescape
    return unescape(re.sub(r"<[^>]*>", " ", value))[:100000]
