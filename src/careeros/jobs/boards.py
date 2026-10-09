from datetime import datetime, timezone

import httpx

from careeros.jobs.arbeitnow import normalize_kind, strip_html
from careeros.jobs.models import JobListing, JobQuery, SourceResult
from careeros.jobs.sources import matches_query


class GreenhouseSource:
    def __init__(self, client: httpx.Client, board_ids: list[str]):
        self.client, self.board_ids = client, board_ids[:30]
        self.name = "greenhouse"

    def fetch(self, query: JobQuery) -> SourceResult:
        return self._fetch(query)

    def _fetch(self, query):
        jobs, bad = [], 0
        for board_id in self.board_ids:
            response = self.client.get(f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs", params={"content": "true"})
            response.raise_for_status()
            values = response.json().get("jobs", [])
            for row in values:
                try:
                    location = (row.get("location") or {}).get("name", "")
                    raw_kind = row.get("metadata") or []
                    raw_kind = " ".join(str(item.get("value", "")) for item in raw_kind if isinstance(item, dict))
                    job = JobListing("greenhouse:" + board_id, str(row["id"]), row["title"], board_id, location, normalize_kind(raw_kind + " " + row["title"]), row["absolute_url"], strip_html(row.get("content") or ""), row.get("updated_at"), datetime.now(timezone.utc).isoformat(), "remote" in location.lower(), original_kind=raw_kind)
                    if matches_query(job, query):
                        jobs.append(job)
                except (KeyError, TypeError, ValueError):
                    bad += 1
        return SourceResult(jobs, [f"Skipped {bad} malformed listing" + ("s" if bad != 1 else "")] if bad else [])


class LeverSource:
    def __init__(self, client: httpx.Client, site_ids: list[str]):
        self.client, self.site_ids = client, site_ids[:30]
        self.name = "lever"

    def fetch(self, query: JobQuery) -> SourceResult:
        jobs, bad = [], 0
        for site_id in self.site_ids:
            response = self.client.get(f"https://api.lever.co/v0/postings/{site_id}", params={"mode": "json"})
            response.raise_for_status()
            values = response.json()
            if not isinstance(values, list):
                raise ValueError("Lever returned an invalid listing collection")
            for row in values:
                try:
                    categories = row.get("categories") or {}
                    location = categories.get("location") or ""
                    raw_kind = categories.get("commitment") or ""
                    job = JobListing("lever:" + site_id, str(row["id"]), row["text"], site_id, location, normalize_kind(raw_kind + " " + row["text"]), row["hostedUrl"], strip_html(row.get("descriptionPlain") or row.get("description") or ""), None, datetime.now(timezone.utc).isoformat(), "remote" in location.lower(), original_kind=raw_kind)
                    if matches_query(job, query):
                        jobs.append(job)
                except (KeyError, TypeError, ValueError):
                    bad += 1
        return SourceResult(jobs, [f"Skipped {bad} malformed listing" + ("s" if bad != 1 else "")] if bad else [])
