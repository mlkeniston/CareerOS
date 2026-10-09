from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class ProfileInput(BaseModel):
    name: str = Field(default="", max_length=100)
    summary: str = Field(default="", max_length=2000)
    target_roles: list[str] = Field(default_factory=list, max_length=20)
    preferred_locations: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=20)


class ResumeInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=200000)


@router.get("/api/profile")
def get_profile(request: Request):
    return request.app.state.profile_repository.get()


@router.put("/api/profile")
def update_profile(payload: ProfileInput, request: Request):
    for name, values in (("target role", payload.target_roles), ("location", payload.preferred_locations), ("skill", payload.skills)):
        if any(not item.strip() or len(item) > 120 for item in values):
            raise HTTPException(422, f"Each {name} must contain 1–120 characters")
    return request.app.state.profile_repository.update(payload.name, payload.summary, payload.target_roles, payload.preferred_locations, payload.skills)


@router.post("/api/resumes", status_code=201)
def create_resume(payload: ResumeInput, request: Request):
    try:
        resume = request.app.state.resume_repository.create(payload.name, payload.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _resume_json(resume)


@router.get("/api/resumes")
def list_resumes(request: Request):
    return [{"id": item.id, "name": item.name, "created_at": item.created_at, "updated_at": item.updated_at} for item in request.app.state.resume_repository.list()]


@router.get("/api/resumes/{resume_id}")
def get_resume(resume_id: str, request: Request):
    resume = request.app.state.resume_repository.get(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")
    return _resume_json(resume)


@router.put("/api/resumes/{resume_id}")
def update_resume(resume_id: str, payload: ResumeInput, request: Request):
    try:
        resume = request.app.state.resume_repository.update(resume_id, payload.name, payload.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not resume:
        raise HTTPException(404, "Resume not found")
    return _resume_json(resume)


def _resume_json(resume):
    return {"id": resume.id, "name": resume.name, "text": resume.text, "created_at": resume.created_at, "updated_at": resume.updated_at}
