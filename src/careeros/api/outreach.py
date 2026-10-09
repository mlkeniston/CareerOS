from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from careeros.outreach.models import CONNECTION_NOTE_MAX_LENGTH, OutreachMessage

router = APIRouter()


class OutreachDraftInput(BaseModel):
    connection_note: str = Field(min_length=1, max_length=CONNECTION_NOTE_MAX_LENGTH)
    follow_up_message: str = Field(min_length=1, max_length=8000)
    evidence: list[str] = Field(max_length=12)


@router.get("/api/outreach")
def list_outreach(request: Request):
    return [_outreach_json(item, request) for item in request.app.state.outreach_service.list()]


@router.get("/api/outreach/{draft_id}")
def get_outreach(draft_id: str, request: Request):
    item = request.app.state.outreach_service.get(draft_id)
    if item is None:
        raise HTTPException(404, "Outreach draft not found")
    return _outreach_json(item, request)


@router.put("/api/outreach/{draft_id}/draft")
def edit_outreach(draft_id: str, payload: OutreachDraftInput, request: Request):
    try:
        item = request.app.state.outreach_service.edit(draft_id, OutreachMessage.parse(payload.model_dump()))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return _outreach_json(item, request)


@router.post("/api/outreach/{draft_id}/approve")
def approve_outreach(draft_id: str, request: Request):
    try:
        item = request.app.state.outreach_service.approve(draft_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": item.id, "status": item.status}


@router.get("/api/outreach/{draft_id}/export")
def export_outreach(draft_id: str, request: Request):
    try:
        content = request.app.state.outreach_service.export_text(draft_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(content, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="careeros-outreach-{draft_id[:8]}.txt"'})


def _outreach_json(item, request: Request) -> dict:
    job = request.app.state.job_repository.get(item.job_id)
    task = request.app.state.queue.get(item.task_id) if item.task_id else None
    status = "interrupted" if item.status == "preparing" and task and task.status == "interrupted" else item.status
    return {
        "id": item.id,
        "job_id": item.job_id,
        "resume_id": item.resume_id,
        "task_id": item.task_id,
        "status": status,
        "task_status": task.status if task else None,
        "task_error": task.error if task else None,
        "task_provider": task.provider if task else None,
        "job_title": job.title if job else "Saved job",
        "company": job.company if job else "",
        "job_url": job.url if job else None,
        "draft": item.draft,
        "updated_at": item.updated_at,
    }
