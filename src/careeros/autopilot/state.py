from __future__ import annotations

from careeros.db import Database
from careeros.queue import now


def dispatch_is_open(conn, fingerprint: str) -> bool:
    """Keep active and successful fingerprints; release failed work for retry."""
    row = conn.execute(
        "SELECT d.kind, d.task_id, t.status FROM autopilot_dispatches d "
        "JOIN tasks t ON t.id=d.task_id WHERE d.fingerprint=?",
        (fingerprint,),
    ).fetchone()
    if row is None:
        return False
    if row["status"] != "failed":
        return True
    if row["kind"] == "application":
        conn.execute(
            "UPDATE applications SET status='failed', updated_at=? WHERE task_id=? AND status='preparing'",
            (now(), row["task_id"]),
        )
    elif row["kind"] == "portfolio":
        conn.execute(
            "UPDATE portfolio_proposals SET status='failed', updated_at=? WHERE task_id=? AND status='preparing'",
            (now(), row["task_id"]),
        )
    elif row["kind"] == "outreach":
        conn.execute(
            "UPDATE outreach_drafts SET status='failed', updated_at=? WHERE task_id=? AND status='preparing'",
            (now(), row["task_id"]),
        )
    conn.execute("DELETE FROM autopilot_dispatches WHERE fingerprint=?", (fingerprint,))
    return False


class AutopilotState:
    def __init__(self, db: Database):
        self.db = db

    def get(self) -> dict:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_row(conn)
            row = conn.execute(
                "SELECT enabled, last_discovery_queued_at FROM autopilot_state WHERE id=1"
            ).fetchone()
            conn.commit()
        return {
            "enabled": bool(row["enabled"]),
            "last_discovery_queued_at": row["last_discovery_queued_at"],
        }

    def get_error(self) -> str | None:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_row(conn)
            row = conn.execute("SELECT last_error FROM autopilot_state WHERE id=1").fetchone()
            conn.commit()
        return row["last_error"]

    def set_enabled(self, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_row(conn)
            conn.execute("UPDATE autopilot_state SET enabled=? WHERE id=1", (int(enabled),))
            row = conn.execute(
                "SELECT enabled, last_discovery_queued_at FROM autopilot_state WHERE id=1"
            ).fetchone()
            conn.commit()
        return {
            "enabled": bool(row["enabled"]),
            "last_discovery_queued_at": row["last_discovery_queued_at"],
        }

    def record_error(self, message: str) -> None:
        safe = (message or "Autopilot scheduler failed").replace("\n", " ").strip()[:240]
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_row(conn)
            conn.execute("UPDATE autopilot_state SET last_error=? WHERE id=1", (safe,))
            conn.commit()

    def clear_error(self) -> None:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_row(conn)
            conn.execute("UPDATE autopilot_state SET last_error=NULL WHERE id=1")
            conn.commit()

    @staticmethod
    def _ensure_row(conn) -> None:
        conn.execute("INSERT OR IGNORE INTO autopilot_state(id, enabled) VALUES(1, 1)")
