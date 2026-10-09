from __future__ import annotations

from datetime import datetime, timedelta, timezone

from careeros.db import Database
from careeros.queue import TaskQueue


class AutopilotScheduler:
    def __init__(
        self,
        db: Database,
        queue: TaskQueue,
        interval: timedelta = timedelta(hours=6),
    ):
        if interval <= timedelta(0):
            raise ValueError("interval must be positive")
        self.db, self.queue, self.interval = db, queue, interval

    def maybe_enqueue_discovery(self, now: datetime | None = None) -> str | None:
        stamp = _utc(now or datetime.now(timezone.utc))
        stamp_text = stamp.isoformat(timespec="seconds")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO autopilot_state(id, enabled) VALUES(1, 1)")
            state = conn.execute(
                "SELECT enabled, last_discovery_queued_at FROM autopilot_state WHERE id=1"
            ).fetchone()
            if not state["enabled"]:
                conn.commit()
                return None
            active = conn.execute(
                "SELECT 1 FROM tasks WHERE kind='job_discovery' AND status IN ('queued','running') LIMIT 1"
            ).fetchone()
            if active:
                conn.commit()
                return None
            last = state["last_discovery_queued_at"]
            if last and stamp < _utc(datetime.fromisoformat(last)) + self.interval:
                conn.commit()
                return None
            task_id = self.queue.enqueue_in_transaction(
                conn, "job_discovery", {}, "ollama", cloud_confirmed=False
            )
            conn.execute(
                "UPDATE autopilot_state SET last_discovery_queued_at=?, last_error=NULL WHERE id=1",
                (stamp_text,),
            )
            conn.commit()
        return task_id


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
