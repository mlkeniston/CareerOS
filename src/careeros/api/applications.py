import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
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


class RevisionPreviewInput(BaseModel):
    provider: str = Field(pattern="^(ollama|openai)$")
    findings: list[dict] = Field(default_factory=list, max_length=100)


@router.post('/api/applications/{application_id}/revision-preview')
def preview_revision(application_id: str, payload: RevisionPreviewInput, request: Request):
    try:
        data, token = request.app.state.application_service.preview_revision(application_id, payload.provider, payload.findings)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'sent_data': data, 'preview_token': token, 'model': data['selected_model']}


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
    reviews = request.app.state.hiring_manager_service.history(application_id)
    with request.app.state.db.connect() as conn:
        rows = conn.execute("SELECT payload_json FROM tasks WHERE kind='hiring_manager' AND json_extract(payload_json,'$.application_id')=? ORDER BY created_at,id", (application_id,)).fetchall()
        export = conn.execute('SELECT exported_at FROM application_exports WHERE application_id=? AND draft_version=?', (application_id, item.draft_version)).fetchone()
    contexts = {json.loads(row['payload_json'])['cycle']: json.loads(row['payload_json'])['review_context']['draft'] for row in rows}
    for review in reviews:
        review['reviewed_draft'] = contexts.get(review['cycle'])
    manager_task = request.app.state.queue.get(item.manager_task_id) if item.manager_task_id else None
    return {"rejection_reason": item.rejection_reason, "exported_at": export['exported_at'] if export else None,
            "manager_task_status": manager_task.status if manager_task else None,
            "manager_task_error": manager_task.error if manager_task else None,
            "id": item.id, "job_id": item.job_id, "resume_id": item.resume_id, "task_id": item.task_id, "status": status, "draft": item.draft, "job_title": job.title if job else "Saved job", "task_status": task.status if task else None, "task_error": task.error if task else None, "task_provider": task.provider if task else None, "snapshot": item.snapshot, "snapshot_hash": item.snapshot_hash, "provider": item.provider, "model": item.model, "draft_version": item.draft_version, "clearance_stale": item.clearance_stale, "manager_cycle": item.manager_cycle, "manager_task_id": item.manager_task_id, "hold_reason": item.hold_reason, "hiring_reviews": reviews}


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
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": item.id, "status": item.status}


class RejectInput(BaseModel):
    reason: StrictStr = Field(default='', max_length=2000)


@router.post('/api/applications/{application_id}/reject')
def reject_application(application_id: str, payload: RejectInput, request: Request):
    try:
        item = request.app.state.application_service.reject(application_id, payload.reason)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'id': item.id, 'status': item.status, 'rejection_reason': item.rejection_reason}


class EvidenceInput(BaseModel):
    name: StrictStr = Field(min_length=1, max_length=120)
    value: StrictStr = Field(min_length=1, max_length=500)
    confirm_accurate: bool = False


@router.post('/api/applications/{application_id}/evidence')
def attest_evidence(application_id: str, payload: EvidenceInput, request: Request):
    from careeros.profiles.repository import validate_eligibility_facts
    if not request.app.state.application_service.get(application_id):
        raise HTTPException(404, 'Application not found')
    if not payload.confirm_accurate:
        raise HTTPException(409, 'Confirm that this fact is accurate before saving it as local evidence')
    profile = request.app.state.profile_repository.get()
    facts = {**profile.eligibility_facts, payload.name.strip(): payload.value.strip()}
    try:
        validate_eligibility_facts(facts)
        request.app.state.profile_repository.update(profile.name, profile.summary, profile.target_roles,
                                                     profile.preferred_locations, profile.skills, facts)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'requires_new_application': True, 'message': 'Fact saved locally. Prepare a new application to include it in a fixed evidence snapshot.'}


@router.get('/api/applications/{application_id}/export')
def export_application(application_id: str, request: Request):
    try:
        path = request.app.state.application_service.export_package(application_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, 'The local package could not be written. Check available disk space and try again.') from exc
    return FileResponse(path, media_type='application/zip', filename=path.name)
