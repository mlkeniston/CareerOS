from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from careeros.planner.gateway import PaidUseConfirmationRequired, ProviderUnavailable
from careeros.portfolio.models import PortfolioBrief
from careeros.portfolio.paths import UnsafePortfolioPath
from careeros.portfolio.service import ExistingPortfolioFile, InvalidProposal

router = APIRouter()


class ProposalInput(BaseModel):
    project_id: str = Field(min_length=1, max_length=48)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=8000)
    provider: str = Field(pattern="^(ollama|openai)$")
    confirm_cloud: bool = False
    preview_token: str | None = None


class ProposalPreviewInput(BaseModel):
    project_id: str = Field(min_length=1, max_length=48)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=8000)


class ApplyInput(BaseModel):
    replace_existing: list[str] = Field(default_factory=list, max_length=20)


@router.post("/api/portfolio/preview")
def preview_proposal(payload: ProposalPreviewInput, request: Request):
    try:
        brief = PortfolioBrief(payload.project_id, payload.title, payload.description)
        data, token = request.app.state.portfolio_service.preview(brief)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"sent_data": data, "preview_token": token, "model": "gpt-6-luna"}


@router.post("/api/portfolio/proposals", status_code=202)
def create_proposal(payload: ProposalInput, request: Request):
    try:
        brief = PortfolioBrief(payload.project_id, payload.title, payload.description)
        task_id, proposal_id = request.app.state.portfolio_service.create(brief, payload.provider, payload.confirm_cloud, payload.preview_token)
    except PaidUseConfirmationRequired as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"task_id": task_id, "proposal_id": proposal_id, "status": "queued"}


@router.get("/api/portfolio/proposals")
def list_proposals(request: Request):
    proposals = request.app.state.portfolio_service.list()
    for proposal in proposals:
        task = request.app.state.queue.get(proposal["task_id"])
        if proposal["status"] == "preparing" and task and task.status == "interrupted":
            proposal["status"] = "interrupted"
        proposal["task_status"] = task.status if task else None
    return proposals


@router.get("/api/portfolio/projects")
def list_projects(request: Request):
    return request.app.state.portfolio_service.projects()


@router.get("/api/portfolio/proposals/{proposal_id}")
def get_proposal(proposal_id: str, request: Request):
    proposal = request.app.state.portfolio_service.get(proposal_id)
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    try:
        proposal["files"] = request.app.state.portfolio_service.diffs(proposal_id)
    except UnsafePortfolioPath as exc:
        raise HTTPException(409, str(exc)) from exc
    task = request.app.state.queue.get(proposal["task_id"])
    proposal["task_status"] = task.status if task else None
    proposal["task_error"] = task.error if task else None
    proposal["task_provider"] = task.provider if task else None
    if task and task.status in {"failed", "interrupted"}:
        proposal["retry_brief"] = task.payload.get("brief")
        if proposal["status"] == "preparing" and task.status == "interrupted":
            proposal["status"] = "interrupted"
    return proposal


@router.post("/api/portfolio/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, request: Request):
    try:
        proposal = request.app.state.portfolio_service.approve(proposal_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": proposal["id"], "status": proposal["status"]}


@router.post("/api/portfolio/proposals/{proposal_id}/apply")
def apply_proposal(proposal_id: str, payload: ApplyInput, request: Request):
    try:
        applied = request.app.state.portfolio_service.apply(proposal_id, payload.replace_existing)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ExistingPortfolioFile as exc:
        raise HTTPException(409, {"message": str(exc), "paths": exc.paths}) from exc
    except (RuntimeError, InvalidProposal, UnsafePortfolioPath) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"applied": applied}
