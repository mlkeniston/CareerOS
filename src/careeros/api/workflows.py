import json

from fastapi import APIRouter, Query, Request

router = APIRouter()

_PUBLIC_PAYLOAD_FIELDS = ("from_station_id", "to_station_id", "item_type")


@router.get("/api/workspace/handoffs")
def get_handoffs(
    request: Request,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    with request.app.state.db.connect() as conn:
        conn.execute("BEGIN")
        rows = conn.execute(
            "SELECT * FROM workflow_handoffs WHERE id>? ORDER BY id ASC LIMIT ?",
            (after_id, limit),
        ).fetchall()
        latest_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM workflow_handoffs").fetchone()[0])

    events = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        public_payload = {key: payload[key] for key in _PUBLIC_PAYLOAD_FIELDS if key in payload}
        event = {
            "id": row["id"],
            "idempotency_key": row["idempotency_key"],
            "task_id": row["task_id"],
            "object_type": row["object_type"],
            "object_id": row["object_id"],
            "from_worker": row["from_worker"],
            "to_worker": row["to_worker"],
            "event_type": row["event_type"],
            "payload": public_payload,
            "created_at": row["created_at"],
        }
        event.update(public_payload)
        events.append(event)
    return {"events": events, "latest_id": latest_id}
