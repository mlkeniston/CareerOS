from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from difflib import unified_diff
from pathlib import Path

from careeros.db import Database
from careeros.portfolio.paths import PortfolioPaths, UnsafePortfolioPath
from careeros.queue import Task, TaskQueue, now
from careeros.worker import TaskOutcome


class InvalidProposal(ValueError):
    pass


class ExistingPortfolioFile(RuntimeError):
    def __init__(self, paths: list[str]):
        self.paths = paths
        super().__init__("Choose which existing files to replace: " + ", ".join(paths))


class PortfolioService:
    def __init__(self, db: Database, queue: TaskQueue, paths: PortfolioPaths):
        self.db, self.queue, self.paths = db, queue, paths

    def get(self, proposal_id: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM portfolio_proposals WHERE id=?", (proposal_id,)).fetchone()
        return _proposal(row) if row else None

    def list(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM portfolio_proposals ORDER BY updated_at DESC").fetchall()
        return [_proposal(row) for row in rows]

    def summaries(self, limit: int = 100) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT portfolio_proposals.id,project_id,task_id,
                   CASE WHEN portfolio_proposals.status='preparing' AND tasks.status='interrupted' THEN 'interrupted' ELSE portfolio_proposals.status END AS status,
                   title,summary,portfolio_proposals.updated_at,tasks.status AS task_status
                   FROM portfolio_proposals LEFT JOIN tasks ON tasks.id=portfolio_proposals.task_id
                   ORDER BY portfolio_proposals.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def handle_task(self, task: Task) -> TaskOutcome:
        proposal_id = task.payload["proposal_id"]
        proposal = self.get(proposal_id)
        if proposal is None:
            raise LookupError("Portfolio proposal record not found")
        stage = self.paths.proposal_dir(proposal_id)
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE portfolio_proposals SET status='quality_hold',hold_reason=?,updated_at=? WHERE id=? AND status='preparing'",
                ("Manual project briefs are disabled; CareerOS prepares sourced projects automatically.", now(), proposal_id),
            )
        return TaskOutcome("completed", {"proposal_id": proposal_id, "status": "quality_hold"})

    def approve(self, proposal_id: str) -> dict:
        proposal = self.get(proposal_id)
        if not proposal:
            raise LookupError("Proposal not found")
        if proposal["status"] == "approved":
            return proposal
        if proposal["status"] == "quality_hold":
            raise RuntimeError("Project is on quality hold and cannot be approved")
        if proposal["status"] != "needs_review":
            raise RuntimeError("Only a complete proposal can be approved")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM portfolio_proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise LookupError("Proposal not found")
            if row["status"] == "quality_hold":
                raise RuntimeError("Project is on quality hold and cannot be approved")
            if row["status"] != "needs_review":
                raise RuntimeError("Only a complete proposal can be approved")
            self._require_passed_qa(conn, proposal_id)
            conn.execute("UPDATE portfolio_proposals SET status='approved',updated_at=? WHERE id=? AND status='needs_review'", (now(), proposal_id))
            conn.commit()
        return self.get(proposal_id)

    def diffs(self, proposal_id: str) -> list[dict]:
        proposal = self.get(proposal_id)
        if not proposal:
            raise LookupError("Proposal not found")
        result = []
        for item in proposal["files"]:
            dest = self.paths.destination(proposal["project_id"], item["path"])
            exists = dest.exists()
            safe_to_replace = True
            if exists and not dest.is_file():
                safe_to_replace = False
                before = []
            elif exists and dest.stat().st_size > 200000:
                safe_to_replace = False
                before = ["[Existing file is larger than the 200 KB preview limit.]\n"]
            elif exists:
                try:
                    before = dest.read_text(encoding="utf-8").splitlines(keepends=True)
                except UnicodeDecodeError:
                    safe_to_replace = False
                    before = ["[Existing file is not UTF-8 text.]\n"]
            else:
                before = []
            after = item["content"].splitlines(keepends=True)
            diff = "".join(unified_diff(before, after, fromfile="existing/" + item["path"], tofile="proposed/" + item["path"]))
            result.append({**item, "exists": exists, "safe_to_replace": safe_to_replace, "diff": diff})
        return result

    def apply(self, proposal_id: str, replace_existing: list[str]) -> list[str]:
        proposal = self.get(proposal_id)
        if not proposal:
            raise LookupError("Proposal not found")
        if proposal["status"] == "quality_hold":
            raise RuntimeError("Project is on quality hold and cannot be applied")
        if proposal["status"] != "approved":
            raise RuntimeError("Approve the proposal before applying files")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_passed_qa(conn, proposal_id)
            conn.commit()
        items = proposal["files"]
        normalized_replace = set(replace_existing)
        proposed_paths = {item["path"] for item in items}
        if not normalized_replace <= proposed_paths:
            raise InvalidProposal("Replacement list must match proposed relative paths")
        targets: list[tuple[str, Path, str, bytes | None]] = []
        collisions = []
        for item in items:
            target = self.paths.destination(proposal["project_id"], item["path"])
            if target.exists() and item["path"] not in normalized_replace:
                collisions.append(item["path"])
            backup = None
            if target.exists() and item["path"] in normalized_replace:
                if not target.is_file() or target.stat().st_size > 200000:
                    raise InvalidProposal("Only UTF-8 text files up to 200 KB can be replaced")
                try:
                    target.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise InvalidProposal("Only UTF-8 text files up to 200 KB can be replaced") from exc
                backup = target.read_bytes()
            targets.append((item["path"], target, item["content"], backup))
        if collisions:
            raise ExistingPortfolioFile(collisions)
        staged: list[tuple[str, Path, Path, bytes | None]] = []
        replaced: list[tuple[Path, bytes | None]] = []
        try:
            for relative, target, content, backup in targets:
                self.paths.destination(proposal["project_id"], relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".careeros-", delete=False) as handle:
                    handle.write(content)
                    temp = Path(handle.name)
                staged.append((relative, target, temp, backup))
            for relative, target, temp, backup in staged:
                os.replace(temp, target)
                replaced.append((target, backup))
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._require_passed_qa(conn, proposal_id)
                changed = conn.execute("UPDATE portfolio_proposals SET status='applied',updated_at=? WHERE id=? AND status='approved'", (now(), proposal_id)).rowcount
                if changed != 1:
                    raise RuntimeError("Project approval changed before files were applied")
                conn.commit()
            return [relative for relative, _, _, _ in staged]
        except Exception:
            for target, backup in reversed(replaced):
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(backup)
            raise
        finally:
            for _, _, temp, _ in staged:
                temp.unlink(missing_ok=True)

    def projects(self) -> list[str]:
        if not self.paths.root.exists():
            return []
        return sorted(child.name for child in self.paths.root.iterdir() if not child.is_symlink() and child.is_dir() and child.name != ".staging" and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", child.name))

    @staticmethod
    def _require_passed_qa(conn, proposal_id: str) -> None:
        row = conn.execute("SELECT status FROM project_qa_runs WHERE proposal_id=? ORDER BY cycle DESC LIMIT 1", (proposal_id,)).fetchone()
        if row is None or row["status"] != "passed":
            raise RuntimeError("A passing independent Project QA review is required")

def _proposal(row: sqlite3.Row) -> dict:
    files = json.loads(row["files_json"])
    keys = set(row.keys())
    return {"id": row["id"], "project_id": row["project_id"], "task_id": row["task_id"], "status": row["status"], "title": row["title"], "summary": row["summary"], "files": files, "updated_at": row["updated_at"], "source_urls": json.loads(row["source_urls_json"]) if "source_urls_json" in keys else [], "manifest": json.loads(row["manifest_json"]) if "manifest_json" in keys else {}, "hold_reason": row["hold_reason"] if "hold_reason" in keys else None, "engineering_fingerprint": row["engineering_fingerprint"] if "engineering_fingerprint" in keys else None}
