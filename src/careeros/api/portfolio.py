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
    raise HTTPException(410, "CareerOS now discovers project ideas and prepares them automatically; manual briefs are disabled.")


@router.post("/api/portfolio/proposals", status_code=202)
def create_proposal(payload: ProposalInput, request: Request):
    raise HTTPException(410, "CareerOS creates portfolio projects from public ideas automatically; manual briefs are disabled.")


@router.get("/api/portfolio/proposals")
def list_proposals(request: Request):
    proposals = request.app.state.portfolio_service.list()
    for proposal in proposals:
        task = request.app.state.queue.get(proposal["task_id"])
        if proposal["status"] == "preparing" and task and task.status == "interrupted":
            proposal["status"] = "interrupted"
        proposal["task_status"] = task.status if task else None
        proposal["qa_history"] = [_qa_record(item) for item in request.app.state.project_qa_service.history(proposal["id"])]
        latest = request.app.state.project_qa_service.latest(proposal["id"])
        proposal["latest_qa"] = _qa_record(latest) if latest else None
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
    proposal["qa_history"] = [_qa_record(item) for item in request.app.state.project_qa_service.history(proposal_id)]
    latest = request.app.state.project_qa_service.latest(proposal_id)
    proposal["latest_qa"] = _qa_record(latest) if latest else None
    if task and task.status in {"failed", "interrupted"}:
        proposal["retry_brief"] = task.payload.get("brief")
        if proposal["status"] == "preparing" and task.status == "interrupted":
            proposal["status"] = "interrupted"
    return proposal


def _qa_record(item):
    if item is None:
        return None
    return {
        "proposal_id": item.proposal_id, "cycle": item.cycle, "status": item.status,
        "deterministic_report": item.deterministic_report, "critique": item.critique,
        "provider": item.provider, "model": item.model, "created_at": item.created_at,
    }


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
