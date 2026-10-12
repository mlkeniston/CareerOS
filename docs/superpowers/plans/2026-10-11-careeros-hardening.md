# CareerOS Reliability Hardening Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task. The user authorized implementation in the current conversation.

**Goal:** Fix the stress-test findings while preserving CareerOS's local-first, human-approved workflow.

**Architecture:** Keep FastAPI, SQLite, and static JavaScript. Make task completion atomic with its prepared domain record, isolate feed discovery from model work, bound parallel board fetches, apply preferred locations when automatic workers choose roles, and suspend the office renderer when it is not visible.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, vanilla JavaScript, Node's built-in test runner.

**Spec:** `docs/superpowers/specs/2026-10-09-careeros-mvp-design.md` (approved MVP design, especially Failure behavior, Testing and acceptance, and Approval and privacy controls).

## Global Constraints

- Ollama remains the default and no provider may be selected automatically as a fallback.
- Every OpenAI task remains explicitly confirmed; interrupted cloud tasks are not retried automatically.
- Applications, outreach, and portfolio changes remain human reviewed; no external submission, sending, publishing, or generated-code execution is added.
- Tests use temporary SQLite databases, fake planners, and mocked feeds; do not call live services.
- Stress and regression commands set `CAREEROS_DATA_DIR` to a fresh temporary directory before importing `careeros.main`.
- Bound configured employer-board concurrency to five requests at once.

## Review Focus

- Importing `careeros.main` must not initialize or migrate the default user database.
- A crash between handler work and queue completion must not repeat a successful model result or strand partial portfolio staging.
- Invalid upstream JSON must return a refresh error and preserve cached jobs.
- Preferred locations must constrain automatic application and outreach selection while an empty preference list preserves current broad matching.
- The office animation and two-second polling must stop while its screen or browser tab is hidden and resume on return.

---

### Task 1: Remove import-time database initialization

**Files:**
- Modify: `src/careeros/main.py`
- Modify: `src/careeros/cli.py`
- Test: `tests/test_app.py`

**Interfaces:** Keep `create_app(settings: Settings | None = None) -> FastAPI`. The CLI constructs the app and passes it directly to Uvicorn.

- [x] **Step 1: Write a subprocess test** that sets `CAREEROS_DATA_DIR` to a nonexistent temporary path, imports `careeros.main`, and asserts that neither the directory nor its database exists afterward.
- [x] **Step 2: Run the test in isolation** with `CAREEROS_DATA_DIR` also set for pytest's imported test app; confirm the import-side-effect assertion fails against the current module-level `app = create_app()`.
- [x] **Step 3: Remove module-level app creation** and change `careeros.cli.main()` to call `uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)`.
- [x] **Step 4: Rerun the import test and CLI tests**; confirm the module import leaves the path absent and the CLI passes a constructed FastAPI app to Uvicorn.

### Task 2: Make worker lanes independent and task transitions safe

**Files:**
- Modify: `src/careeros/main.py`
- Modify: `src/careeros/queue.py`
- Modify: `src/careeros/worker.py`
- Test: `tests/test_queue.py`, `tests/test_worker.py`, `tests/test_applications.py`, `tests/test_outreach.py`, `tests/test_portfolio.py`, `tests/test_autopilot.py`, `tests/test_workspace_api.py`

**Interfaces:** Add `TaskQueue.finish_in_transaction(conn, task_id, result, status)`. `finish()` delegates to it. Repeating an identical finalization is idempotent; a transition from any other non-running state raises `InvalidTaskTransition`. `fail()` accepts running work only and is idempotent for an identical failed result. Keep `app.state.worker` for application/outreach/portfolio work and add `app.state.discovery_worker` for `job_discovery` only.

- [x] **Step 1: Write queue transition tests** for queued-to-finish rejection, running-to-finish, identical repeat finish, rejection of conflicting terminal finish, queued-to-fail rejection, and running-to-fail.
- [x] **Step 2: Run those tests** and confirm failures identify the current unguarded queue updates.
- [x] **Step 3: Write a head-of-line test** with a blocking fake discovery source; while its discovery worker waits, run a queued application task in `app.state.worker` and assert it reaches review before releasing the source.
- [x] **Step 4: Run the lane test** and confirm it fails while both kinds share one worker.
- [x] **Step 5: Add the dedicated discovery worker** and start/stop both workers in the lifespan; keep the scheduler tick on the discovery lane.
- [x] **Step 6: Implement queue state guards** using `WHERE status='running'`; check the existing row to allow only an exact idempotent repeat.
- [x] **Step 7: Update fixture setup** in workspace and autopilot tests to claim tasks before calling `finish()` or `fail()`.
- [x] **Step 8: Run queue, worker, workspace, and lane tests**; confirm status transitions and separation pass.

### Task 3: Commit prepared records and queue results atomically

**Files:**
- Modify: `src/careeros/applications/service.py`
- Modify: `src/careeros/outreach/service.py`
- Modify: `src/careeros/portfolio/service.py`
- Test: `tests/test_applications.py`, `tests/test_outreach.py`, `tests/test_portfolio.py`

**Interfaces:** Each handler uses the same SQLite connection to save its final prepared record and task result. A handler encountering an already reviewed/approved record returns its stored outcome without another planner call. A failed record does not trigger regeneration. Portfolio staging for a still-preparing proposal is safely cleared and rebuilt on local replay.

- [x] **Step 1: Write application and outreach crash-window tests** that claim a task, call its service handler without `Worker.run_once()`, then assert the domain record and queue task are both already `needs_review`; assert the fake planner was called once.
- [x] **Step 2: Run these tests** and confirm the queue still says `running` after the handler has saved its record.
- [x] **Step 3: Write a portfolio replay test** with a stale partial staging directory; recover and rerun the local task, then assert the proposal is reviewable, only proposed files remain, and queue state is `needs_review`.
- [x] **Step 4: Run this test** and confirm the current `exist_ok=False` staging creation fails.
- [x] **Step 5: Persist each final domain result and task result in one transaction** using `finish_in_transaction`; preserve worker-level completion as an idempotent repeat.
- [x] **Step 6: Add already-finished record checks** before planner invocation and clear only a safe, non-symlink proposal staging directory for a still-preparing local task.
- [x] **Step 7: Run application, outreach, portfolio, and queue tests**; confirm review gates and cloud no-retry behavior remain intact.

### Task 4: Harden and bound public-board refresh

**Files:**
- Modify: `src/careeros/jobs/arbeitnow.py`
- Modify: `src/careeros/jobs/boards.py`
- Modify: `src/careeros/api/jobs.py`
- Test: `tests/test_job_sources.py`, `tests/test_jobs_api.py`

**Interfaces:** Greenhouse and Lever use a shared helper that runs at most five board requests concurrently, validates top-level JSON and listing collections, keeps successful board results when another board fails, and returns per-board warnings. If every configured board fails, the connector raises one safe feed exception. The API reports a source-level error for unexpected connector failures while keeping cached listings searchable.

- [x] **Step 1: Add malformed top-level response tests** for Arbeitnow, Greenhouse, and Lever using `httpx.MockTransport`; assert each fails with a feed-data exception rather than `AttributeError`.
- [x] **Step 2: Add a refresh API test** whose source raises an unexpected parser exception; assert the route responds 200 with a source error and cached roles remain available.
- [x] **Step 3: Add a bounded-concurrency test** using a fake client that counts active requests across multiple board IDs; assert peak activity is greater than one and never exceeds five.
- [x] **Step 4: Run these tests** and confirm malformed feed inputs currently cause exceptions and board fetching is sequential.
- [x] **Step 5: Validate response shapes, fetch configured boards with a five-thread maximum, aggregate successful results and warnings, and log unexpected refresh exceptions without returning exception text to the user.**
- [x] **Step 6: Run job-source, jobs API, and discovery tests**; verify cached search and partial-feed results remain available.

### Task 5: Apply saved location preferences to automatic role selection

**Files:**
- Modify: `src/careeros/autopilot/discovery.py`
- Test: `tests/test_autopilot.py`, `tests/test_outreach.py`
- Modify: `README.md`

**Interfaces:** Add a pure helper that accepts a job and a list of preferred locations. No preferences means unrestricted. Multiple preferences are ORed. `Remote` matches listings flagged remote or whose location says remote. City preferences match case-insensitively against the listing location. Apply this predicate only when selecting automatic application/outreach roles.

- [x] **Step 1: Write discovery tests** proving a nonmatching city is skipped, a matching city is selected, `Remote` selects a remote listing, and an empty preference list keeps existing behavior.
- [x] **Step 2: Run the location tests** and confirm the current selector ignores the saved preferences.
- [x] **Step 3: Filter application/outreach candidates by the profile's saved preferred locations** before ranking them.
- [x] **Step 4: Document that preferences guide automatic draft selection and do not filter public listings out of the searchable cache.**
- [x] **Step 5: Run discovery and outreach tests** and confirm location behavior without changing portfolio market-skill analysis.

### Task 6: Suspend office animation and polling off-screen

**Files:**
- Modify: `src/careeros/static/office-renderer.js`
- Modify: `src/careeros/static/app.js`
- Test: `tests/office-renderer.test.mjs`

**Interfaces:** Add `OfficeRenderer.setActive(active: boolean)`. Inactive renderers cancel their animation frame; active renderers draw once and resume the frame loop unless reduced motion is enabled. App navigation and document visibility control activity and the two-second office polling interval.

- [x] **Step 1: Add a non-reduced-motion canvas harness test** that records requested/cancelled animation frames; assert deactivate cancels the pending frame, reactivate schedules one, and destroy leaves none.
- [x] **Step 2: Run the renderer test** and confirm `setActive` is missing.
- [x] **Step 3: Implement active-state-aware frame scheduling** and call it from station navigation and tab visibility handling; stop polling while away from the office or while the tab is hidden.
- [x] **Step 4: Run all renderer tests and `node --check` on each static JavaScript module.**

### Task 7: Verify the complete hardening set

**Files:**
- Test: full Python and JavaScript suites
- Review: `README.md` and the MVP spec

- [x] **Step 1: Run Python tests with a fresh `CAREEROS_DATA_DIR` set before import.**
- [x] **Step 2: Run `node --test tests/*.test.mjs` and syntax-check all static JavaScript modules.**
- [x] **Step 3: Repeat queue concurrency against a `TemporaryDirectory` database and assert unique claims plus a single discovery enqueue under simultaneous scheduler ticks.**
- [x] **Step 4: Verify the Git diff contains only intended source, test, documentation, and plan changes; verify no network, model, or live user database was used.**
- [x] **Step 5: Report any remaining limitation explicitly; do not claim real-browser or external-provider verification.**
