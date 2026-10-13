from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

from careeros.queue import Task, TaskQueue
from careeros.workflows.errors import RetryableTaskError


@dataclass(slots=True)
class TaskOutcome:
    status: Literal["completed", "needs_review"]
    result: dict


class Worker:
    def __init__(self, queue: TaskQueue, handlers: dict[str, Callable[[Task], TaskOutcome]] | None = None,
                 before_claim: Callable[[], None] | None = None,
                 failure_handlers: dict[str, Callable[[Task, str], None]] | None = None):
        self.queue = queue
        self.handlers = dict(handlers or {})
        self.failure_handlers = dict(failure_handlers or {})
        self.before_claim = before_claim
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def register(self, kind: str, handler: Callable[[Task], TaskOutcome]) -> None:
        self.handlers[kind] = handler

    def register_failure_handler(self, kind: str, handler: Callable[[Task, str], None]) -> None:
        self.failure_handlers[kind] = handler

    def run_once(self) -> bool:
        if self.before_claim is not None:
            try:
                self.before_claim()
            except Exception:
                logging.getLogger(__name__).exception("before_claim hook failed")
        task = self.queue.claim_next(set(self.handlers))
        if task is None:
            return False
        try:
            outcome = self.handlers[task.kind](task)
            self.queue.finish(task.id, outcome.result, outcome.status)
        except RetryableTaskError as exc:
            safe = _safe_error(exc)
            if task.provider != "ollama" or not self.queue.retry(
                task.id, safe, delay_seconds=min(60 * 2 ** (task.attempt_count - 1), 900)
            ):
                self.queue.fail(task.id, safe)
                self._notify_failure(task, safe)
        except Exception as exc:
            safe = _safe_error(exc)
            self.queue.fail(task.id, safe)
            self._notify_failure(task, safe)
        return True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="careeros-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                worked = False
            if not worked:
                self._stop.wait(0.5)

    def _notify_failure(self, task: Task, message: str) -> None:
        handler = self.failure_handlers.get(task.kind)
        if handler is None:
            return
        try:
            handler(task, message)
        except Exception:
            logging.getLogger(__name__).exception("task failure handler failed for %s", task.kind)


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    if not message:
        return "Task failed. Check the local provider and try again."
    return message[:240]
