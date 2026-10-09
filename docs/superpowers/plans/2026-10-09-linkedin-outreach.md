# LinkedIn Outreach Department Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an automatic, local-first LinkedIn Outreach department that prepares messages from relevant roles for the user's review and manual use.

**Architecture:** Add a SQLite-backed outreach draft domain and queue handler, dispatch one deduplicated Ollama task from job discovery when a profile and resume are available, and expose edit/approve/export routes. Add the worker to the real workspace snapshot and neon pixel office, with a compact draft station for review and copy.

**Tech Stack:** Python 3, FastAPI, SQLite, Pydantic, existing planner gateway, vanilla JavaScript, Canvas pixel renderer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-careeros-linkedin-outreach.md`

## Global Constraints

- “Ollama stays the default and the only planner available to unattended work.”
- “A person must review and approve each packet before any external application submission.”
- “Unattended tasks always use the local planner, never OpenAI.”
- CareerOS runs locally with SQLite persistence and no new frontend build dependency.
- LinkedIn account access, people scraping/discovery, and outbound sending remain unavailable.

## Review Focus

- Missing resume or target roles must not block role discovery; outreach remains waiting and queues no personal draft.
- Repeated scans and failed tasks must not create duplicate open drafts for the same role/resume.
- Malformed or ungrounded planner output must not create a partial draft or claim it was sent.
- An unapproved draft must not be exported or approved after its state changes.
- Workspace snapshots must not expose resumes, full messages, private job descriptions, API keys, or task payloads.
- Outreach generation must require loopback Ollama, and a remote endpoint must not create a retrying blocked task.
- Connection notes must fit LinkedIn's current Basic invitation limit of 200 characters.

---

### Task 1: Persistent outreach drafts and review API

**Files:**
- Create: `src/careeros/migrations/006_outreach.sql`
- Create: `src/careeros/outreach/__init__.py`
- Create: `src/careeros/outreach/models.py`
- Create: `src/careeros/outreach/service.py`
- Create: `src/careeros/api/outreach.py`
- Modify: `src/careeros/main.py`
- Modify: `tests/test_outreach.py`

**Interfaces:**
- `OutreachService.create_automatic(job_id: str, resume_id: str, fingerprint: str) -> tuple[OutreachDraft, str] | None`
- `OutreachService.handle_task(task: Task) -> TaskOutcome`
- `OutreachService.list() -> list[OutreachDraft]`
- `OutreachService.edit(draft_id: str, draft: OutreachMessage) -> OutreachDraft`
- `OutreachService.approve(draft_id: str) -> OutreachDraft`
- `OutreachService.export_text(draft_id: str) -> str`
- Routes: `GET /api/outreach`, `GET /api/outreach/{id}`, `PUT /api/outreach/{id}/draft`, `POST /api/outreach/{id}/approve`, and `GET /api/outreach/{id}/export`.

- [x] Write failing tests for local automatic enqueue/dedupe, validated generation, edit/approve/export, and rejection of unapproved export.
- [x] Run the focused outreach tests and confirm they fail because the outreach service/routes do not exist.
- [x] Implement the migration, validated message model, service, API, and handler registration using the existing application patterns.
- [x] Run focused outreach tests and confirm they pass; record status transitions and provider choice.

### Task 2: Automatic role-driven dispatch and live office state

**Files:**
- Modify: `src/careeros/autopilot/discovery.py`
- Modify: `src/careeros/api/workspace.py`
- Modify: `src/careeros/main.py`
- Modify: `tests/test_autopilot.py` (or the repository's existing discovery test module)
- Modify: `tests/test_workspace_api.py`

**Interfaces:**
- Discovery selects the highest-ranked technology role that overlaps the saved target roles, then calls `create_automatic` with an outreach fingerprint scoped to role and resume.
- Workspace exposes a `linkedin-outreach` worker with task kind `outreach` and adds `outreach_to_review` to counts.

- [x] Write failing tests for automatic outreach dispatch, missing personal materials, repeat-scan deduplication, and queue-to-worker state mapping.
- [x] Run the focused dispatch/workspace tests and confirm the missing outreach behavior.
- [x] Implement one-role-per-scan dispatch using Ollama and include only safe worker labels/counts in the workspace snapshot.
- [x] Run the focused tests and confirm they pass without exposing private draft content.

### Task 3: Neon office station and draft review screen

**Files:**
- Modify: `src/careeros/static/office-layout.js`
- Modify: `src/careeros/static/office-renderer.js` only if rendering behavior requires a change
- Modify: `src/careeros/static/index.html`
- Modify: `src/careeros/static/app.js`
- Modify: `src/careeros/static/office.css`
- Create: `tests/office-layout.test.mjs`

**Interfaces:**
- Worker identity and station: `linkedin-outreach`, station id `outreach-team-01`.
- Outreach station screen reads the API draft list and supports editing, approval, and clipboard copy after approval.

- [x] Add a Node built-in UI layout check and verify it fails because the pixel worker/room/station mapping is missing.
- [x] Add a compact outreach booth that fits the current top-down office, a distinct neon-magenta worker, and keyboard-accessible navigation to its station.
- [x] Connect the screen to the persistent API; allow copy only after approval and report clipboard errors clearly.
- [x] Run the UI check and inspect the live office in a browser at desktop and narrow widths.

### Task 4: Setup documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-09-careeros-office-autopilot-design.md` only if needed to point to this approved feature addendum

- [x] Explain that loopback Ollama prepares drafts automatically from a relevant role, profile, and resume; the user chooses a contact and sends manually.
- [x] Run the complete Python suite and JavaScript syntax check; inspect all output.
- [x] Confirm the SQLite upgrade works against the existing schema and the app still starts locally.
- [x] Review the diff for unintended LinkedIn/network side effects, unsafe claims, and any automatic paid provider path.
