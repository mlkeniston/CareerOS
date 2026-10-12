# CareerOS Workflow Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the durable queue and handoff primitives that let CareerOS run autonomous departments and animate only persisted workflow transitions.

**Architecture:** Keep SQLite as the source of truth. Add an idempotent handoff event ledger, bounded retry scheduling for explicitly transient local tasks, and a read-only workspace event endpoint. The office polls new events and turns them into short-lived, data-driven interactions without replaying old events after reload.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, vanilla JavaScript, Node's built-in test runner.

**Spec:** `docs/superpowers/specs/2026-10-11-careeros-autonomous-workflows-design.md` (approved; Components and data flow, UI and interaction, Runtime, provider, and privacy behavior, Failure handling, Verification plan).

## Global Constraints

- Persist queue state, review cycles, gate outcomes, evidence references, project test reports, handoffs, user decisions, and export/apply history in SQLite.
- Use transactional/idempotent dispatch so restarts and repeated scans do not duplicate active applications or projects.
- Local Ollama is used for scheduled autonomous drafting, hiring review, project creation, and QA. Limit concurrent inference to one task by default.
- A cloud error ends that attempt; do not silently fall back or automatically retry an OpenAI request.
- When the app closes or the Mac sleeps, processing stops; durable queued tasks continue after restart when the app and required local model are available.
- Do not treat UI animation as task state; it must reflect persisted transitions.

## Review Focus

- A repeated transition write with the same idempotency key must produce one event; a different key must preserve a separate cycle.
- A handoff created during a failed domain transaction must roll back with the domain update.
- A just-created or future retry must not be claimable before its `available_at` time.
- A cloud task must never enter the automatic retry path, including after a timeout or process restart.
- A browser reload must set the handoff cursor to the current high-water mark and skip events that happened while the page was closed.

---

### Task 1: Persist workflow handoffs

**Files:**
- Create: `src/careeros/workflows/__init__.py`
- Create: `src/careeros/workflows/models.py`
- Create: `src/careeros/workflows/repository.py`
- Create: `src/careeros/migrations/007_workflow_handoffs.sql`
- Modify: `src/careeros/db.py`
- Create: `tests/test_workflow_repository.py`

**Interfaces:**
- Produces: `HandoffEvent(id: int, idempotency_key: str, task_id: str, object_type: str, object_id: str, from_worker: str, to_worker: str, event_type: str, payload: dict, created_at: str)`.
- Produces: `WorkflowRepository.record(conn, *, idempotency_key, task_id, object_type, object_id, from_worker, to_worker, event_type, payload) -> HandoffEvent` and `WorkflowRepository.after(event_id: int, limit: int = 50) -> list[HandoffEvent]`; `latest_id() -> int` returns `0` for an empty ledger.
- Consumes: the existing `Database.connect()` transaction pattern and `TaskQueue.now()` timestamp format.

- [ ] **Step 1: Write tests for one-time, ordered, and transactional handoffs.**
In `tests/test_workflow_repository.py`, define `running_task(db)` by initializing `TaskQueue(db)`, enqueueing an Ollama task, and claiming it; use the existing `db` fixture from `tests/conftest.py`.

```python
def test_handoffs_are_idempotent_and_ordered(db, running_task):
    repo = WorkflowRepository(db)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        first = repo.record(
            conn, idempotency_key="application:a:manager:1", task_id=running_task.id,
            object_type="application", object_id="a", from_worker="resume-analyst",
            to_worker="hiring-manager", event_type="draft-submitted", payload={"item": "resume"},
        )
        duplicate = repo.record(
            conn, idempotency_key="application:a:manager:1", task_id=running_task.id,
            object_type="application", object_id="a", from_worker="resume-analyst",
            to_worker="hiring-manager", event_type="draft-submitted", payload={"item": "resume"},
        )
        conn.commit()
    assert duplicate.id == first.id
    assert repo.after(0) == [first]
    assert repo.latest_id() == first.id

    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            repo.record(
                conn, idempotency_key="application:a:manager:2", task_id=running_task.id,
                object_type="application", object_id="a", from_worker="resume-analyst",
                to_worker="hiring-manager", event_type="draft-submitted", payload={"item": "resume"},
            )
            raise RuntimeError("rollback test")
    assert repo.latest_id() == first.id
```

- [ ] **Step 2: Run the repository test and confirm the missing table/interface is the failure.**

Run: `pytest tests/test_workflow_repository.py::test_handoffs_are_idempotent_and_ordered -q`
Expected: FAIL because `WorkflowRepository` and migration 007 do not exist.

- [ ] **Step 3: Add the migration and repository methods.** Create `workflow_handoffs` with an autoincrement integer primary key, unique `idempotency_key`, task foreign key, object/worker/event fields, JSON payload, and timestamp. Add an index on `(id, created_at)`. In `record`, use `INSERT ... ON CONFLICT(idempotency_key) DO NOTHING`, then select and return the stored row; if the key exists with different immutable fields, raise `ValueError` instead of silently reusing it. Validate payload by JSON encode/decode and cap encoded payload at 16 KB.

- [ ] **Step 4: Run the repository tests.**

Run: `pytest tests/test_workflow_repository.py -q`
Expected: PASS for same-key idempotence, distinct sequential IDs, ordered reads, malformed JSON-safe payload rejection, and rollback when the caller rolls back.

- [ ] **Step 5: Commit only this task's files.**

```bash
git add src/careeros/workflows src/careeros/migrations/007_workflow_handoffs.sql src/careeros/db.py tests/test_workflow_repository.py
git commit -m "feat: persist workflow handoffs"
```

### Task 2: Schedule bounded retries for transient local failures

**Files:**
- Create: `src/careeros/migrations/008_task_retries.sql`
- Modify: `src/careeros/queue.py`
- Modify: `src/careeros/worker.py`
- Create: `src/careeros/workflows/errors.py`
- Modify: `tests/test_queue.py`, `tests/test_worker.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `RetryableTaskError(message: str)` for a service to mark an explicitly transient failure.
- Produces: `TaskQueue.retry(task_id: str, message: str, delay_seconds: int, max_attempts: int = 3) -> bool`. It accepts only a running Ollama task, returns `True` when requeued, and returns `False` after the attempt limit so the worker can fail it visibly.
- Modifies: `Task` adds `attempt_count: int` and `available_at: str`; `claim_next()` claims only due queued tasks and increments `attempt_count` atomically.
- Test fixture: add `queue` to `tests/conftest.py` as `TaskQueue(db)`; use the existing `db` fixture for every test database.

- [ ] **Step 1: Add retry boundary tests.** Add tests asserting first and second retry requests requeue with a future due time, the third attempt is not requeued, and an OpenAI task cannot be requeued.

```python
def test_retry_is_bounded_and_cloud_is_never_requeued(queue):
    local_id = queue.enqueue("application", {}, "ollama")
    assert queue.claim_next({"application"}).id == local_id
    assert queue.retry(local_id, "Ollama offline", delay_seconds=300, max_attempts=3)
    assert queue.get(local_id).status == "queued"
    assert queue.get(local_id).attempt_count == 1

    cloud_id = queue.enqueue("application", {}, "openai", cloud_confirmed=True)
    assert queue.claim_next({"application"}).id == cloud_id
    with pytest.raises(InvalidTaskTransition):
        queue.retry(cloud_id, "request timed out", delay_seconds=1)
```

- [ ] **Step 2: Run the targeted retry tests and confirm they fail on the absent retry API.**

Run: `pytest tests/test_queue.py::test_retry_is_bounded_and_cloud_is_never_requeued -q`
Expected: FAIL because `attempt_count`, `available_at`, and `retry()` are not implemented.

- [ ] **Step 3: Add the queue migration and guarded state transition.** Migration 008 adds `attempt_count INTEGER NOT NULL DEFAULT 0` and nullable `available_at TEXT` to `tasks`; `NULL` means immediately due. Increment attempts in the same `BEGIN IMMEDIATE` claim transaction. In `retry()`, require provider `ollama`, `status='running'`, a positive delay no greater than 3600 seconds, and a positive limit; set `status='queued'`, `available_at=now()+delay`, and a safe 240-character diagnostic. Keep migration 007 immutable, and keep `finish()` and `fail()` transition guards intact.

- [ ] **Step 4: Make the worker retry only the explicit transient exception.** Catch `RetryableTaskError` before generic exceptions; call `queue.retry(task.id, ..., delay_seconds=min(60 * 2 ** (task.attempt_count - 1), 900))`; if it returns false, call `fail()`. All other errors fail immediately. Keep `PaidUseConfirmationRequired`, cloud errors, invalid model JSON, and sandbox safety failures non-retryable.

- [ ] **Step 5: Run queue and worker tests.**

Run: `pytest tests/test_queue.py tests/test_worker.py -q`
Expected: PASS, including future-task non-claim, local retry ceiling, and cloud no-retry.

- [ ] **Step 6: Commit only this task's files.**

```bash
git add src/careeros/migrations/008_task_retries.sql src/careeros/queue.py src/careeros/worker.py src/careeros/workflows/errors.py tests/test_queue.py tests/test_worker.py tests/conftest.py
git commit -m "feat: retry transient local tasks safely"
```

### Task 3: Deliver handoff events to the office renderer

**Files:**
- Create: `src/careeros/api/workflows.py`
- Modify: `src/careeros/main.py`
- Modify: `src/careeros/api/workspace.py`
- Modify: `src/careeros/static/app.js`
- Modify: `src/careeros/static/office-renderer.js`
- Modify: `tests/test_workspace_api.py`, `tests/office-renderer.test.mjs`

**Interfaces:**
- Produces: `GET /api/workspace/handoffs?after_id=<int>&limit=<1..100>` returning `{events: [...], latest_id: int}` with event fields from Task 1 plus `from_station_id`, `to_station_id`, and `item_type` when present in payload. `/api/workspace` adds `handoff_cursor: int` for reload initialization.
- Produces: `OfficeRenderer.playHandoffs(events: HandoffEvent[]): void`; renderer ignores unknown event types and stores recognized events as transient animation state only.
- Consumes: Task 1 repository, the existing `/api/workspace` snapshot, and the existing `OfficeRenderer.update(snapshot)` polling loop.

- [ ] **Step 1: Write API cursor and renderer tests.** In `tests/test_workspace_api.py`, define `add_test_handoff(repo, task, idempotency_key)` to insert one handoff in a transaction. Verify the route returns only IDs greater than `after_id`, preserves `latest_id` when no rows match, and the renderer accepts known handoffs while ignoring unknown types. Add a renderer reload test proving initial cursor setup does not enqueue earlier events.

```python
def test_handoff_endpoint_uses_exclusive_cursor(client, workflow_repository, running_task):
    add_test_handoff(workflow_repository, running_task, idempotency_key="first")
    add_test_handoff(workflow_repository, running_task, idempotency_key="second")
    response = client.get("/api/workspace/handoffs?after_id=1")
    assert response.status_code == 200
    assert [event["id"] for event in response.json()["events"]] == [2]
    assert response.json()["latest_id"] == 2
```

- [ ] **Step 2: Run the targeted tests and confirm the route/method are absent.**

Run: `pytest tests/test_workspace_api.py::test_handoff_endpoint_uses_exclusive_cursor -q && node --test tests/office-renderer.test.mjs`
Expected: FAIL on the missing route and `playHandoffs` method.

- [ ] **Step 3: Add the API route and register it.** Validate `after_id >= 0` and `1 <= limit <= 100`; read events and the high-water mark in one database connection; return only persisted event data. Do not return profile, resume, employer-page, or model prompt content in this endpoint.

- [ ] **Step 4: Add the renderer's transient handoff queue.** Map only `draft-submitted`, `critique-returned`, `project-submitted`, `project-defect-returned`, and `project-qa-passed` to document/project/ticket/green-pass tokens. Interpolate between worker world positions for 700 ms, expire each event after 2 seconds, skip reduced-motion playback while retaining the final static state, and never synthesize an event from a worker status alone.

- [ ] **Step 5: Poll new events and suppress stale playback.** On initial office snapshot, set `lastHandoffId` to the snapshot's current `handoff_cursor`; after each workspace poll, request events after that cursor, pass them to `playHandoffs`, and update the cursor to `latest_id`. Keep the cursor in memory only, so a page reload takes a fresh high-water mark and does not replay closed-page history.

- [ ] **Step 6: Run API and renderer tests.**

Run: `pytest tests/test_workspace_api.py -q && node --test tests/office-renderer.test.mjs`
Expected: PASS for exclusive cursor, high-water initialization, recognized interactions, unknown-event ignore, reduced motion, and no duplicate playback after consecutive polls.

- [ ] **Step 7: Commit only this task's files.**

```bash
git add src/careeros/api/workflows.py src/careeros/main.py src/careeros/api/workspace.py src/careeros/static/app.js src/careeros/static/office-renderer.js tests/test_workspace_api.py tests/office-renderer.test.mjs
git commit -m "feat: animate persisted department handoffs"
```

### Task 4: Verify workflow foundation migrations and restart behavior

**Files:**
- Test: `tests/test_workflow_repository.py`, `tests/test_queue.py`, `tests/test_worker.py`, `tests/test_workspace_api.py`, `tests/office-renderer.test.mjs`
- Modify: `README.md`

**Interfaces:** Preserve all interfaces from Tasks 1–3. Setup documentation explains that the office shows queued local work only while CareerOS and the Mac are awake, and queued items survive restart.

- [ ] **Step 1: Add a migration-upgrade test** that initializes a database at migration 006 with queued and completed task rows, initializes again, and asserts old rows remain readable plus migration 007 is recorded.
- [ ] **Step 2: Run the migration test and confirm it exposes any ordering or data-loss error.**

Run: `pytest tests/test_workflow_repository.py::test_upgrade_from_006_preserves_tasks -q`
Expected: PASS only after the migration preserves pre-existing queue rows and applies once.

- [ ] **Step 3: Document queue and handoff behavior** in `README.md`, including recovery after app restart, local-only retries, and the fact that visual movement follows stored workflow transitions.
- [ ] **Step 4: Run focused foundation verification.**

Run: `pytest tests/test_workflow_repository.py tests/test_queue.py tests/test_worker.py tests/test_workspace_api.py -q && node --test tests/office-renderer.test.mjs`
Expected: PASS; no live job feed, Ollama, or OpenAI call is made.

- [ ] **Step 5: Commit only this task's files.**

```bash
git add README.md tests/test_workflow_repository.py
git commit -m "docs: explain persistent workflow state"
```
