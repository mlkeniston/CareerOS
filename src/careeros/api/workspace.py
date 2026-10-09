from datetime import datetime, timezone

from fastapi import APIRouter, Request

from careeros.autopilot.matching import score_technology_role

router = APIRouter()

_WORKERS = (
    ("job-hunter", "Job Hunters", "job-hunters-01", "cyan", "job_discovery"),
    ("resume-analyst", "Resume Team", "resume-team-01", "green", None),
    ("application-prep", "Application Team", "application-team-01", "amber", "application"),
    ("portfolio-engineer", "Engineering Team", "engineering-team-01", "purple", "portfolio"),
    ("director", "Dispatch", "dispatch-01", "coral", None),
)
_TASK_LABELS = {
    "job_discovery": "Scan public listings",
    "application": "Prepare application draft",
    "portfolio": "Prepare portfolio proposal",
}
_STATUS_PRIORITY = {"running": 0, "queued": 1, "needs_review": 2, "failed": 3, "interrupted": 4}


@router.get("/api/workspace")
def get_workspace(request: Request):
    db = request.app.state.db
    queue = request.app.state.queue
    tasks = queue.list(limit=1000)
    by_kind = {kind: _current_task(tasks, kind) for *_prefix, kind in _WORKERS if kind}
    state = request.app.state.autopilot_state.get()
    interval = request.app.state.autopilot_scheduler.interval
    last = state["last_discovery_queued_at"]
    if not state["enabled"]:
        next_discovery_at = None
    elif last:
        next_discovery_at = (datetime.fromisoformat(last) + interval).isoformat(timespec="seconds")
    else:
        next_discovery_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with db.connect() as conn:
        jobs_found = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        drafts_to_review = conn.execute("SELECT COUNT(*) FROM applications WHERE status='needs_review'").fetchone()[0]
        proposals_to_review = conn.execute("SELECT COUNT(*) FROM portfolio_proposals WHERE status='needs_review'").fetchone()[0]
        approved_applications = conn.execute("SELECT COUNT(*) FROM applications WHERE status='approved'").fetchone()[0]
        applied_proposals = conn.execute("SELECT COUNT(*) FROM portfolio_proposals WHERE status='applied'").fetchone()[0]
        provider_row = conn.execute("SELECT value FROM settings WHERE key='planner_provider'").fetchone()

    selected_provider = provider_row[0] if provider_row else request.app.state.settings.planner_provider
    if selected_provider == "openai" and not request.app.state.settings.openai_api_key:
        selected_provider = "ollama"
    local_planner = request.app.state.gateway.planners.get("ollama")
    health = getattr(local_planner, "health", None)
    model_state = health() if callable(health) else "offline"
    model_name = request.app.state.settings.ollama_model
    selected_model = "gpt-6-luna" if selected_provider == "openai" else model_name

    has_resume = request.app.state.resume_repository.most_recent() is not None
    profile = request.app.state.profile_repository.get()
    has_target_roles = bool([role for role in (profile.target_roles or []) if isinstance(role, str) and role.strip()])
    recent_jobs = request.app.state.job_repository.recent(limit=500)
    jobs_matched = sum(1 for job in recent_jobs if score_technology_role(job)[0] >= 70)
    worker_items = []
    for worker_id, department, station_id, color, kind in _WORKERS:
        task = by_kind.get(kind) if kind else None
        worker = {
            "id": worker_id,
            "department": department,
            "station_id": station_id,
            "color": color,
        }
        if task is not None:
            worker.update(_worker_task(task))
        else:
            status, label = _waiting_state(worker_id, state["enabled"], has_resume, has_target_roles, model_state)
            worker.update({"status": status, "task_label": label})
        worker_items.append(worker)

    activity = [_activity(task) for task in tasks[:10]]
    return {
        "autopilot": {
            "enabled": state["enabled"],
            "last_discovery_queued_at": last,
            "next_discovery_at": next_discovery_at,
            "last_error": request.app.state.autopilot_state.get_error(),
        },
        "workers": worker_items,
        "counts": {
            "jobs_found": jobs_found,
            "jobs_matched": jobs_matched,
            "tasks_shipped": approved_applications + applied_proposals,
            "drafts_to_review": drafts_to_review,
            "proposals_to_review": proposals_to_review,
        },
        "activity": activity,
        "model": {
            "selected_provider": selected_provider,
            "autopilot_provider": "ollama",
            "name": model_name,
            "selected_model": selected_model,
            "state": model_state,
        },
    }


def _current_task(tasks, kind: str):
    eligible = [task for task in tasks if task.kind == kind and task.status in _STATUS_PRIORITY]
    if not eligible:
        return None
    return min(eligible, key=lambda task: (_STATUS_PRIORITY[task.status], task.created_at or "", task.id))


def _worker_task(task) -> dict:
    label = _TASK_LABELS.get(task.kind, "Work task")
    if task.status == "needs_review":
        label = {
            "application": "Application draft ready for review",
            "portfolio": "Proposal ready for review",
        }.get(task.kind, "Task ready for review")
    elif task.status == "failed":
        label = {
            "job_discovery": "Listing scan failed",
            "application": "Application preparation failed",
            "portfolio": "Portfolio proposal failed",
        }.get(task.kind, "Task failed")
    elif task.status == "interrupted":
        label = "Task interrupted"
    result = {
        "status": "working" if task.status == "running" else "waiting" if task.status == "queued" else task.status,
        "task_id": task.id,
        "task_kind": task.kind,
        "task_label": label,
    }
    if task.status == "running" and task.updated_at:
        result["since"] = task.updated_at
    return result


def _waiting_state(worker_id: str, enabled: bool, has_resume: bool, has_target_roles: bool, model_state: str) -> tuple[str, str]:
    if worker_id == "job-hunter":
        return ("paused", "Job discovery is paused") if not enabled else ("idle", "Waiting for the next listing scan")
    if worker_id in {"resume-analyst", "application-prep"}:
        if not has_resume:
            return "waiting", "Add a resume to enable draft preparation"
        if not has_target_roles:
            return "waiting", "Add target roles to enable draft preparation"
        return "waiting", "Waiting for a suitable discovered role" if model_state == "ready" else "Waiting for the local model"
    if worker_id == "portfolio-engineer":
        return "waiting", "Watching for recurring skills in public listings"
    return "idle", "No dispatch task is active"


def _activity(task) -> dict:
    if task.kind == "job_discovery" and task.status == "completed":
        count = (task.result or {}).get("jobs_found")
        if isinstance(count, int) and count >= 0:
            label = f"Indexed {count} roles"
        else:
            label = "Listing scan completed"
    else:
        base = _TASK_LABELS.get(task.kind, "Work task")
        label = {
            "queued": f"{base} queued",
            "running": base,
            "needs_review": "Work ready for review",
            "failed": "Task failed",
            "interrupted": "Task interrupted",
            "completed": f"{base} completed",
        }.get(task.status, "Task updated")
    return {
        "task_id": task.id,
        "task_kind": task.kind,
        "status": task.status,
        "updated_at": task.updated_at,
        "label": label,
    }
