from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HandoffEvent:
    id: int
    idempotency_key: str
    task_id: str
    object_type: str
    object_id: str
    from_worker: str
    to_worker: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
