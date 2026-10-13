from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx

from careeros.jobs.arbeitnow import normalize_kind, strip_html
from careeros.jobs.models import JobListing, JobQuery, SourceResult
from careeros.jobs.sources import matches_query, SourceUnavailableError


MAX_BOARD_FETCH_WORKERS = 5


def _fetch_boards(board_ids, fetch_board) -> SourceResult:
    if not board_ids:
        return SourceResult([], [])
    jobs, warnings = [], []
    successes = 0
    failures = []
    with ThreadPoolExecutor(max_workers=min(MAX_BOARD_FETCH_WORKERS, len(board_ids))) as pool:
        futures = [(board_id, pool.submit(fetch_board, board_id)) for board_id in board_ids]
        for board_id, future in futures:
            try:
                board_jobs, skipped = future.result()
            except Exception as exc:
                failures.append(exc)
                warnings.append(f"{board_id}: feed unavailable or malformed")
                continue
            successes += 1
            jobs.extend(board_jobs)
            if skipped:
                warnings.append(f"{board_id}: skipped {skipped} malformed listing" + ("s" if skipped != 1 else ""))
    if failures and successes == 0:
        raise SourceUnavailableError("All configured employer boards returned unavailable or invalid data", failures)
    return SourceResult(jobs, warnings)


class GreenhouseSource:
    def __init__(self, client: httpx.Client, board_ids: list[str]):
        self.client, self.board_ids = client, board_ids[:30]
        self.name = "greenhouse"

    def fetch(self, query: JobQuery) -> SourceResult:
        return _fetch_boards(self.board_ids, lambda board_id: self._fetch_board(board_id, query))

    def _fetch_board(self, board_id, query):
        response = self.client.get(f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs", params={"content": "true"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Greenhouse returned an invalid response object")
        values = payload.get("jobs", [])
        if not isinstance(values, list):
            raise ValueError("Greenhouse returned an invalid listing collection")
        jobs, bad = [], 0
        for row in values:
            if not isinstance(row, dict):
                bad += 1
                continue
            try:
                raw_location = row.get("location")
                location = raw_location.get("name", "") if isinstance(raw_location, dict) else ""
                raw_kind = row.get("metadata") or []
                raw_kind = " ".join(str(item.get("value", "")) for item in raw_kind if isinstance(item, dict))
                title = row["title"]
                job = JobListing("greenhouse:" + board_id, str(row["id"]), title, board_id, location, normalize_kind(raw_kind + " " + title), row["absolute_url"], strip_html(row.get("content") or ""), row.get("updated_at"), datetime.now(timezone.utc).isoformat(), "remote" in location.lower(), original_kind=raw_kind,
                    source_url=f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs/{row['id']}",
                    employer_url=row['absolute_url'], application_url=row['absolute_url'],
                    requisition_id=str(row['requisition_id']) if row.get('requisition_id') is not None else None)
                if matches_query(job, query):
                    jobs.append(job)
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                bad += 1
        return jobs, bad


class LeverSource:
    def __init__(self, client: httpx.Client, site_ids: list[str]):
        self.client, self.site_ids = client, site_ids[:30]
        self.name = "lever"

    def fetch(self, query: JobQuery) -> SourceResult:
        return _fetch_boards(self.site_ids, lambda site_id: self._fetch_site(site_id, query))

    def _fetch_site(self, site_id, query):
        response = self.client.get(f"https://api.lever.co/v0/postings/{site_id}", params={"mode": "json"})
        response.raise_for_status()
        values = response.json()
        if not isinstance(values, list):
            raise ValueError("Lever returned an invalid listing collection")
        jobs, bad = [], 0
        for row in values:
            if not isinstance(row, dict):
                bad += 1
                continue
            try:
                categories = row.get("categories") or {}
                if not isinstance(categories, dict):
                    categories = {}
                location = categories.get("location") or ""
                raw_kind = categories.get("commitment") or ""
                title = row["text"]
                created = row.get('createdAt')
                published = datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if isinstance(created, (int, float)) else created if isinstance(created, str) else None
                job = JobListing("lever:" + site_id, str(row["id"]), title, site_id, location, normalize_kind(raw_kind + " " + title), row["hostedUrl"], strip_html(row.get("descriptionPlain") or row.get("description") or ""), published, datetime.now(timezone.utc).isoformat(), "remote" in location.lower(), original_kind=raw_kind,
                    source_url=f"https://api.lever.co/v0/postings/{site_id}/{row['id']}",
                    employer_url=row['hostedUrl'], application_url=row.get('applyUrl'),
                    requisition_id=str(row['requisitionId']) if row.get('requisitionId') is not None else None)
                if matches_query(job, query):
                    jobs.append(job)
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                bad += 1
        return jobs, bad
