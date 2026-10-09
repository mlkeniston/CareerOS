from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    task = request.app.state.queue.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"id": task.id, "kind": task.kind, "provider": task.provider, "status": task.status, "result": task.result, "error": task.error}
