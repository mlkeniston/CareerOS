from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class AutopilotInput(BaseModel):
    enabled: bool


@router.get("/api/autopilot")
def get_autopilot(request: Request):
    return _status(request)


@router.put("/api/autopilot")
def update_autopilot(payload: AutopilotInput, request: Request):
    request.app.state.autopilot_state.set_enabled(payload.enabled)
    return _status(request)


def _status(request: Request) -> dict:
    state = request.app.state.autopilot_state.get()
    last = state["last_discovery_queued_at"]
    if not state["enabled"]:
        next_at = None
    elif last:
        next_at = (datetime.fromisoformat(last) + request.app.state.autopilot_scheduler.interval).isoformat(timespec="seconds")
    else:
        next_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        **state,
        "next_discovery_at": next_at,
        "last_error": request.app.state.autopilot_state.get_error(),
    }
