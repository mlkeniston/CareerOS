from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, StrictStr

from careeros.applications.models import ApplicationDraft
from careeros.planner.gateway import PaidUseConfirmationRequired, ProviderUnavailable

router = APIRouter()


class PrepareInput(BaseModel):
    job_id: str
    resume_id: str
    provider: str = Field(pattern="^(ollama|openai)$")
    confirm_cloud: bool = False
    preview_token: str | None = None


class ApplicationPreviewInput(BaseModel):
    job_id: str
    resume_id: str


@router.post("/api/applications/preview")
def preview_application(payload: ApplicationPreviewInput, request: Request):
    try:
        data, token = request.app.state.application_service.preview(payload.job_id, payload.resume_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"sent_data": data, "preview_token": token, "model": data["provider_models"]["openai"]}


class ClaimInput(BaseModel):
    claim_id: StrictStr = Field(min_length=1, max_length=100)
    text: StrictStr = Field(min_length=1, max_length=1000)
    evidence_ids: list[StrictStr] = Field(max_length=5)
    quote_anchors: list[StrictStr] = Field(max_length=5)


class DraftInput(BaseModel):
    resume_text: StrictStr = Field(min_length=1, max_length=30000)
    cover_letter: StrictStr = Field(max_length=30000)
    claims: list[ClaimInput] = Field(max_length=100)
    answers: dict[StrictStr, StrictStr] = Field(default_factory=dict, max_length=30)
    next_steps: list[StrictStr] = Field(default_factory=list, max_length=30)


@router.post("/api/applications", status_code=202)
def create_application(payload: PrepareInput, request: Request):
    try:
        application, task_id = request.app.state.application_service.create(payload.job_id, payload.resume_id, payload.provider, payload.confirm_cloud, payload.preview_token)
    except PaidUseConfirmationRequired as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": application.id, "task_id": task_id, "status": application.status}


@router.get("/api/applications")
def list_applications(request: Request):
    result = []
    for item in request.app.state.application_service.list():
        job = request.app.state.job_repository.get(item.job_id)
        task = request.app.state.queue.get(item.task_id) if item.task_id else None
        status = "interrupted" if item.status == "preparing" and task and task.status == "interrupted" else item.status
        result.append({"id": item.id, "job_id": item.job_id, "job_title": job.title if job else "Saved job", "status": status, "task_status": task.status if task else None, "updated_at": item.updated_at})
    return result


@router.get("/api/applications/{application_id}")
def get_application(application_id: str, request: Request):
    item = request.app.state.application_service.get(application_id)
    if not item:
        raise HTTPException(404, "Application not found")
    job = request.app.state.job_repository.get(item.job_id)
    task = request.app.state.queue.get(item.task_id) if item.task_id else None
    status = "interrupted" if item.status == "preparing" and task and task.status == "interrupted" else item.status
    return {"id": item.id, "job_id": item.job_id, "resume_id": item.resume_id, "task_id": item.task_id, "status": status, "draft": item.draft, "job_title": job.title if job else "Saved job", "task_status": task.status if task else None, "task_error": task.error if task else None, "task_provider": task.provider if task else None, "snapshot": item.snapshot, "snapshot_hash": item.snapshot_hash, "provider": item.provider, "model": item.model, "draft_version": item.draft_version, "clearance_stale": item.clearance_stale}


@router.put("/api/applications/{application_id}/draft")
def edit_application(application_id: str, payload: DraftInput, request: Request):
    try:
        draft = ApplicationDraft.parse(payload.model_dump())
        item = request.app.state.application_service.edit(application_id, draft)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": item.id, "status": item.status, "draft": item.draft}


@router.post("/api/applications/{application_id}/approve")
def approve_application(application_id: str, request: Request):
    try:
        item = request.app.state.application_service.approve(application_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": item.id, "status": item.status}


@router.get("/api/applications/{application_id}/export")
def export_application(application_id: str, request: Request):
    try:
        content = request.app.state.application_service.export_markdown(application_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(content, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="careeros-{application_id[:8]}.md"'})
