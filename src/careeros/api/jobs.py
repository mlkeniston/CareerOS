from datetime import datetime, timezone
import logging

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from careeros.autopilot.matching import score_technology_role
from careeros.jobs.location import is_us_location
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
    jobs = request.app.state.job_repository.search(query, saved_only=saved)
    verifications = _verification_map(request, jobs)
    return [_job_json(job, verifications.get(job.id)) for job in jobs]


@router.post("/api/jobs/refresh")
def refresh_jobs(payload: RefreshInput, request: Request):
    query = JobQuery(payload.text, payload.location, payload.kind, payload.remote_only, 200)
    count, sources = 0, []
    for source in request.app.state.job_sources:
        try:
            result = source.fetch(query)
            count += request.app.state.job_repository.upsert_many(result.jobs)
            sources.append({"name": source.name, "saved": len(result.jobs), "warnings": result.warnings, "error": None})
        except Exception as exc:
            logging.getLogger(__name__).exception("Job source refresh failed")
            if isinstance(exc, httpx.TimeoutException):
                label = "The feed timed out. Cached jobs are still available."
            elif isinstance(exc, httpx.HTTPError):
                label = "The feed request failed. Cached jobs are still available."
            else:
                label = "The feed returned invalid data. Cached jobs are still available."
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
    return _job_json(saved, _get_verification(request, saved.id))


@router.post("/api/jobs/{job_id}/save")
def save_job(job_id: str, request: Request):
    job = request.app.state.job_repository.set_saved(job_id, True)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_json(job, _get_verification(request, job.id))


@router.post("/api/jobs/{job_id}/unsave")
def unsave_job(job_id: str, request: Request):
    job = request.app.state.job_repository.set_saved(job_id, False)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_json(job, _get_verification(request, job.id))


@router.post("/api/jobs/{job_id}/verify")
def verify_job(job_id: str, request: Request):
    repository = request.app.state.job_repository
    job = repository.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not is_us_location(job.location):
        raise HTTPException(409, "Confirm a U.S. location before checking this employer posting")
    service = request.app.state.job_discovery_service
    if service.verifier is None:
        raise HTTPException(503, "Employer verification is not available right now")
    service.check_job(job)
    return _job_json(repository.get(job.id), _get_verification(request, job.id))


def _verification_map(request: Request, jobs: list[JobListing]) -> dict[str, dict]:
    ids = [job.id for job in jobs if job.id]
    if not ids:
        return {}
    return {job_id: _verification_json(value) for job_id, value in request.app.state.job_repository.verifications(ids).items()}


def _get_verification(request: Request, job_id: str) -> dict | None:
    value = request.app.state.job_repository.get_verification(job_id)
    return _verification_json(value) if value else None


def _verification_json(verification) -> dict:
    return {key: verification[key] for key in ('status', 'outcome', 'reason', 'checked_url', 'final_url',
                                              'checked_at', 'evidence_summary', 'attempts', 'next_retry_at')}


def _job_json(job: JobListing, verification: dict | None = None) -> dict:
    score, reasons = score_technology_role(job)
    verification = dict(verification) if verification else {'status': 'not_checked', 'outcome': None,
        'reason': 'Employer check has not run yet.', 'checked_at': None, 'checked_url': None, 'final_url': None,
        'evidence_summary': '', 'attempts': 0, 'next_retry_at': None}
    verification['can_recheck'] = is_us_location(job.location)
    verification['retry_eligible'] = (verification['can_recheck'] and verification['outcome'] == 'transient_error'
                                      and verification['attempts'] < 3 and bool(verification['next_retry_at']))
    return {"id": job.id, "source": job.source, "title": job.title, "company": job.company, "location": job.location, "kind": job.kind, "original_kind": job.original_kind, "remote": job.remote, "url": job.url, "description": job.description, "published_at": job.published_at, "fetched_at": job.fetched_at, "source_url": job.source_url, "employer_url": job.employer_url, "application_url": job.application_url, "requisition_id": job.requisition_id, "source_age": job.source_age, "is_saved": job.is_saved, "technology_score": score, "technology_reasons": reasons, "employer_verification": verification}
