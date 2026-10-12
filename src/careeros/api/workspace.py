from datetime import datetime, timezone

from fastapi import APIRouter, Request

from careeros.autopilot.matching import score_technology_role

router = APIRouter()

_WORKERS = (
    ("job-hunter", "Job Hunters", "job-hunters-01", "cyan", "job_discovery"),
    ("resume-analyst", "Resume Team", "resume-team-01", "green", None),
    ("application-prep", "Application Team", "application-team-01", "amber", "application"),
    ("hiring-manager", "Hiring Manager", "hiring-manager-01", "green", "hiring_manager"),
    ("portfolio-engineer", "Engineering Team", "engineering-team-01", "purple", "portfolio"),
    ("linkedin-outreach", "LinkedIn Outreach", "outreach-team-01", "coral", "outreach"),
    ("director", "Dispatch", "dispatch-01", "coral", None),
)
_TASK_LABELS = {
    "job_discovery": "Scan public listings",
    "application": "Prepare application draft",
    "hiring_manager": "Review application evidence",
    "application_revision": "Revise application locally",
    "portfolio": "Prepare portfolio proposal",
    "outreach": "Prepare LinkedIn outreach draft",
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
        outreach_to_review = conn.execute("SELECT COUNT(*) FROM outreach_drafts WHERE status='needs_review'").fetchone()[0]
        approved_applications = conn.execute("SELECT COUNT(*) FROM applications WHERE status='approved'").fetchone()[0]
        applied_proposals = conn.execute("SELECT COUNT(*) FROM portfolio_proposals WHERE status='applied'").fetchone()[0]
        provider_row = conn.execute("SELECT value FROM settings WHERE key='planner_provider'").fetchone()
        handoff_cursor = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM workflow_handoffs").fetchone()[0])

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
    outreach_service = request.app.state.outreach_service
    outreach_model_state = outreach_service.model_status()
    outreach_model_name = request.app.state.settings.outreach_model
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
        if worker_id == "linkedin-outreach":
            worker.update({"model": outreach_model_name, "model_status": outreach_model_state})
        if task is not None:
            worker.update(_worker_task(task))
        else:
            status, label = _waiting_state(
                worker_id, state["enabled"], has_resume, has_target_roles, model_state,
                outreach_model_state, outreach_model_name,
            )
            worker.update({"status": status, "task_label": label})
        if worker_id == 'hiring-manager':
            worker.update({'gender': 'male', 'provider': 'ollama', 'model': model_name,
                           'model_status': model_state, 'current_item': None, 'latest_verdict': None, 'hold_reason': None})
            manager_task = by_kind.get('hiring_manager')
            active_manager_task = manager_task if manager_task and manager_task.status in {'running', 'queued'} else None
            with db.connect() as conn:
                row = None
                if active_manager_task:
                    application_id = active_manager_task.payload.get('application_id')
                    if application_id:
                        row = conn.execute("SELECT a.*,j.title FROM applications a LEFT JOIN jobs j ON j.id=a.job_id WHERE a.id=?", (application_id,)).fetchone()
                if row is None:
                    row = conn.execute("SELECT a.*,j.title FROM applications a LEFT JOIN jobs j ON j.id=a.job_id ORDER BY CASE a.status WHEN 'manager_review' THEN 0 WHEN 'needs_review' THEN 1 WHEN 'quality_hold' THEN 2 ELSE 3 END,a.updated_at DESC LIMIT 1").fetchone()
                latest = conn.execute('SELECT verdict,model FROM hiring_reviews WHERE application_id=? ORDER BY cycle DESC LIMIT 1', (row['id'],)).fetchone() if row else None
            if row:
                manager_task = active_manager_task or (queue.get(row['manager_task_id']) if row['manager_task_id'] else None)
                worker.update({'status': row['status'], 'current_item': row['title'],
                               'task_id': manager_task.id if manager_task else row['manager_task_id'],
                               'task_label': ('Waiting to review ' if manager_task and manager_task.status == 'queued' else 'Reviewing ') + (row['title'] or 'application'),
                               'latest_verdict': latest['verdict'] if latest else None, 'hold_reason': row['hold_reason']})
                if manager_task:
                    worker['model'] = manager_task.payload.get('selected_model', model_name)
                    if manager_task.status == 'running':
                        worker['status'] = 'working'
                        worker['since'] = manager_task.updated_at
                    elif manager_task.status in {'failed', 'interrupted'} and row['status'] == 'manager_review':
                        worker['status'] = manager_task.status
                if not manager_task or manager_task.status not in {'running', 'queued'}:
                    worker['task_label'] = ('Needs your review: ' if row['status'] == 'needs_review' else 'Approved: ' if row['status'] == 'approved' else 'Reviewing ') + (row['title'] or 'application')
            else:
                worker.update({'status': 'waiting', 'task_label': 'Waiting for an application draft'})
        worker_items.append(worker)

    activity = [_activity(task) for task in tasks[:10]]
    return {
        "handoff_cursor": handoff_cursor,
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
            "outreach_to_review": outreach_to_review,
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
            "outreach": "LinkedIn draft ready for review",
        }.get(task.kind, "Task ready for review")
    elif task.status == "failed":
        label = {
            "job_discovery": "Listing scan failed",
            "application": "Application preparation failed",
            "portfolio": "Portfolio proposal failed",
            "outreach": "LinkedIn outreach preparation failed",
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


def _waiting_state(
    worker_id: str,
    enabled: bool,
    has_resume: bool,
    has_target_roles: bool,
    model_state: str,
    outreach_model_state: str = "ready",
    outreach_model_name: str = "qwen3.5:2b-q4_K_M",
) -> tuple[str, str]:
    if worker_id == "job-hunter":
        return ("paused", "Job discovery is paused") if not enabled else ("idle", "Waiting for the next listing scan")
    if worker_id in {"resume-analyst", "application-prep", "linkedin-outreach"}:
        if worker_id == "linkedin-outreach":
            if outreach_model_state == "remote":
                return "waiting", "LinkedIn outreach needs Ollama on this Mac"
            if outreach_model_state == "offline":
                return "waiting", "Start Ollama on this Mac"
            if outreach_model_state == "model_missing":
                return "waiting", f"Install model with ollama pull {outreach_model_name}"
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
