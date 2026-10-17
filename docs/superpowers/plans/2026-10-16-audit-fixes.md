# CareerOS Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the nine concrete correctness, recovery, performance, and maintenance findings from the 2026-10-16 repository audit.

**Architecture:** Keep the current FastAPI, SQLite, worker, and vanilla JavaScript structure. Fix shared behavior at its existing boundary, expose only the recovery actions the UI needs, and replace large list hydration with summary queries.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, httpx, pytest, browser JavaScript tests.

**Spec:** The ponytail audit delivered in this chat on 2026-10-16.

## Global Constraints

- Keep CareerOS loopback-only and local-first.
- Never submit applications or send outreach.
- Never run generated project code on macOS.
- Do not add dependencies.
- Preserve existing SQLite data through migrations.

## Review Focus

- A declared failing test must make Project QA fail for every supported runtime.
- Retrying a failed review must keep the fixed application snapshot and review cycle.
- OpenAI requests must carry the exact response schema after paid confirmation.
- A database failure during discovery must fail the scan instead of looking successful.
- Long-running histories must not be fully decoded for summary screens.

---

### Task 1: Execute declared QA tests

**Files:** `tests/test_portfolio_sandbox.py`, `src/careeros/portfolio/sandbox.py`

- [x] Add failing tests for exact Python and static manifest test execution.
- [x] Run them and verify the old commands ignore the declared files.
- [x] Build fixed allowlisted commands from the validated manifest.
- [x] Run the focused tests.

### Task 2: Recover failed application review work

**Files:** `tests/test_applications_api.py`, `src/careeros/applications/service.py`, `src/careeros/applications/hiring_manager.py`, `src/careeros/api/applications.py`, `src/careeros/main.py`, `src/careeros/static/app.js`

- [x] Add failing API tests for failed manager and revision retries.
- [x] Persist and expose the failed stage, then requeue the same draft and cycle.
- [x] Add one retry action in the existing review panel.
- [x] Run application and UI tests.

### Task 3: Enforce cloud structured output

**Files:** `tests/test_planner.py`, `src/careeros/planner/openai.py`

- [x] Add a failing request-body test.
- [x] Send the existing response schema through the Responses API JSON format.
- [x] Run planner tests.

### Task 4: Surface discovery infrastructure failures

**Files:** `tests/test_autopilot.py`, `src/careeros/autopilot/discovery.py`

- [x] Add a failing test for a SQLite dispatch error.
- [x] Isolate expected listing failures and re-raise infrastructure errors.
- [x] Run autopilot tests.

### Task 5: Make office polling cheap

**Files:** `tests/test_workspace_api.py`, `src/careeros/api/workspace.py`

- [x] Add tests for one shared cached model health result and bounded task summaries.
- [x] Reuse health state and query only data required by the office.
- [x] Run workspace tests.

### Task 6: Bound summary lists and U.S. filtering

**Files:** repository/service/API modules and their existing tests.

- [x] Add failing tests proving summaries omit large blobs and remain bounded.
- [x] Add summary queries for resumes, applications, and proposals.
- [x] Persist deterministic job location status and filter it in SQL.
- [x] Run repository and API tests.

### Task 7: Correct discovery counts

**Files:** `tests/test_jobs.py`, `src/careeros/jobs/repository.py`

- [x] Add a failing test distinguishing inserted rows from refreshed rows.
- [x] Return inserted counts and keep update behavior unchanged.
- [x] Run job tests.

### Task 8: Remove disabled manual portfolio generation

**Files:** `src/careeros/portfolio/service.py`, `src/careeros/portfolio/models.py`, `src/careeros/api/portfolio.py`, affected tests.

- [x] Remove production methods reachable only through HTTP 410 endpoints.
- [x] Keep the minimal legacy queued-task hold path and active autonomous proposal review/apply code.
- [x] Run portfolio tests.

### Task 9: Verify the complete repository

- [x] Run the full Python suite.
- [x] Run the full Node suite.
- [x] Inspect the final diff and working-tree status.
