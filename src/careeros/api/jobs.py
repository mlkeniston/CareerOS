from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from careeros.jobs.models import JobListing, JobQuery
from careeros.jobs.repository import JobRepository

router = APIRouter()


class RefreshInput(BaseModel):
    text: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=100)
    kind: str = Field(default="", max_length=40)
    remote_only: bool = False


class ManualJobInput(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    company: str = Field(min_length=1, max_length=240)
    location: str = Field(default="", max_length=240)
    kind: str = Field(default="other", max_length=80)
    url: str = Field(min_length=8, max_length=2000)
    description: str = Field(default="", max_length=100000)
    remote: bool = False


@router.get("/api/jobs")
def search_jobs(request: Request, q: str = Query(default="", max_length=200), location: str = Query(default="", max_length=100), kind: str = Query(default="", max_length=40), remote_only: bool = False, saved: bool = False, limit: int = Query(default=100, ge=1, le=500)):
    query = JobQuery(q, location, kind, remote_only, limit)
    return [_job_json(job) for job in request.app.state.job_repository.search(query, saved_only=saved)]


@router.post("/api/jobs/refresh")
def refresh_jobs(payload: RefreshInput, request: Request):
    query = JobQuery(payload.text, payload.location, payload.kind, payload.remote_only, 200)
    count, sources = 0, []
    for source in request.app.state.job_sources:
        try:
            result = source.fetch(query)
            count += request.app.state.job_repository.upsert_many(result.jobs)
            sources.append({"name": source.name, "saved": len(result.jobs), "warnings": result.warnings, "error": None})
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            label = "The feed timed out or returned invalid data." if isinstance(exc, (httpx.TimeoutException, ValueError, KeyError, TypeError)) else "The feed request failed. Cached jobs are still available."
            sources.append({"name": source.name, "saved": 0, "warnings": [], "error": label})
    return {"saved": count, "sources": sources}


@router.post("/api/jobs/manual", status_code=201)
def add_manual_job(payload: ManualJobInput, request: Request):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        listing = JobListing("manual", "pending", payload.title, payload.company, payload.location, payload.kind, payload.url, payload.description, None, stamp, payload.remote, original_kind=payload.kind)
        saved = request.app.state.job_repository.add_manual(listing)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _job_json(saved)


@router.post("/api/jobs/{job_id}/save")
def save_job(job_id: str, request: Request):
    job = request.app.state.job_repository.set_saved(job_id, True)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_json(job)


@router.post("/api/jobs/{job_id}/unsave")
def unsave_job(job_id: str, request: Request):
    job = request.app.state.job_repository.set_saved(job_id, False)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_json(job)


def _job_json(job: JobListing) -> dict:
    return {"id": job.id, "source": job.source, "title": job.title, "company": job.company, "location": job.location, "kind": job.kind, "original_kind": job.original_kind, "remote": job.remote, "url": job.url, "description": job.description, "published_at": job.published_at, "is_saved": job.is_saved}
