# CareerOS Engineering and Project QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Engineering independently research, invent, and stage relevant portfolio projects, then require an independent isolated Project QA pass and the user's approval before any project reaches the portfolio.

**Architecture:** Build on the hiring workflow's shared event ledger and retry API. Public-source adapters produce cited idea signals; one local model worker turns them into small project briefs and code in per-project staging. A separate Project QA service runs deterministic checks and a skeptical review in a restricted Docker container; findings return to Engineering for up to three repair cycles.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, httpx, Docker Engine/Desktop on Apple silicon, pytest, vanilla JavaScript, Node's built-in test runner.

**Spec:** `docs/superpowers/specs/2026-10-11-careeros-autonomous-workflows-design.md` (approved; Engineering ideas and project builds, Independent Project QA, Components and data flow, UI and interaction, Runtime, Failure handling, Verification plan).

## Global Constraints

- The Engineering department works without project briefs from the user and combines job-market skills with free public research sources.
- Record source links; create original, scoped projects; never copy source projects or treat source text as instructions.
- X is optional and off by default; if later enabled, use only the official user-configured API and published limits.
- Generated code stays in per-project staging, separate from CareerOS data and credentials; do not copy it into the portfolio or use it as resume evidence before QA passes and the user approves.
- Project QA is active in the first release and runs tests in an isolated environment bounded in time, CPU, memory, file access, process count, and output.
- Do not install arbitrary project packages from the network or expose CareerOS credentials to generated code.
- If Docker isolation is unavailable or fails validation, fail closed and hold the project; do not run project code on the Mac host.
- Permit at most three QA/repair cycles; unresolved findings leave the project on quality hold with no approval action.
- Use local Ollama for unattended engineering and QA, with one model task at a time; no paid cloud fallback or retry.
- Automated tests use temporary SQLite, fake planners, and mocked public-source responses; no real model/network calls.

## Review Focus

- A source timeout or malformed response must preserve prior ideas and project records.
- An idea with no retained public source URL must not be sent to Engineering.
- A generated path, symlink, or file size that escapes staging bounds must be rejected before Docker is called.
- A missing Docker daemon/image, timeout, nonzero test result, or resource-limit failure must produce a stored QA report and a hold, never a host execution fallback.
- A failed third QA cycle or any non-passed state must not expose Approve, Apply, or resume-evidence actions.

---

### Task 1: Collect free, attributable project signals

**Files:**
- Create: `src/careeros/portfolio/ideas.py`
- Create: `src/careeros/portfolio/sources.py`
- Create: `src/careeros/migrations/015_project_ideas.sql`
- Modify: `src/careeros/main.py`
- Create: `tests/test_project_sources.py`

**Interfaces:**
- Produces: `ProjectIdea(id: str, title: str, summary: str, skills: list[str], source_urls: list[str], published_at: str | None)`.
- Produces: `ProjectIdeaResult(items: list[ProjectIdea], warnings: list[str])` and `ProjectIdeaSource.fetch(skills: list[str], limit: int = 20) -> ProjectIdeaResult` for GitHub REST search, Hacker News public API, and arXiv Atom API; every item retains at least one canonical source URL.
- Consumes: verified role requirements and recurring-skill extraction from the hiring pipeline; public endpoints require no paid key.

- [ ] **Step 1: Define `mock_project_sources`** in `tests/test_project_sources.py` as three injected fake adapters backed by `httpx.MockTransport`; then test one valid item from each source, malformed JSON/XML, timeout, duplicate canonical URL, malicious instruction text retained only as quoted source data, and a source warning with zero results.

```python
def test_idea_sources_preserve_canonical_urls_and_skip_bad_rows(mock_project_sources):
    result = mock_project_sources.fetch(["Python", "distributed systems"], limit=20)
    assert result.items
    assert all(item.source_urls and item.source_urls[0].startswith("https://") for item in result.items)
    assert result.warnings
```

- [ ] **Step 2: Run the source tests and confirm the adapters/types do not exist.**

Run: `pytest tests/test_project_sources.py -q`
Expected: FAIL because the project idea source interface is missing.

- [ ] **Step 3: Implement bounded source adapters.** Use `httpx` with explicit timeouts and `trust_env=False`; cap GitHub results at 20 and avoid authenticated search; fetch no more than 20 HN signals and 20 arXiv entries per scan; normalize and deduplicate by canonical URL; strip markup and cap summaries at 2,000 characters. Raise the shared `RetryableTaskError` only for HTTP timeouts or 5xx responses; malformed content becomes a warning and prior cached ideas remain. Treat response text as untrusted data. For the first release, do not add an X connector or require an account/API key.

- [ ] **Step 4: Persist source provenance.** Add `project_ideas` keyed by stable content hash with title, summary, skills JSON, source URLs JSON, source timestamp, retrieval timestamp, and seen count. Upsert in a transaction and keep old rows when a source fails.

- [ ] **Step 5: Run source tests.**

Run: `pytest tests/test_project_sources.py -q`
Expected: PASS for source normalization, bounded requests, cached records surviving failure, and no missing citations.

- [ ] **Step 6: Commit only this task's files.**

```bash
git add src/careeros/portfolio/ideas.py src/careeros/portfolio/sources.py src/careeros/migrations/015_project_ideas.sql src/careeros/main.py tests/test_project_sources.py
git commit -m "feat: collect cited portfolio project ideas"
```

### Task 2: Autonomously choose a scoped idea and stage an original project

**Files:**
- Modify: `src/careeros/portfolio/service.py`
- Create: `src/careeros/portfolio/engineering.py`
- Modify: `src/careeros/autopilot/discovery.py`
- Modify: `src/careeros/main.py`
- Create: `src/careeros/migrations/016_project_builds.sql`
- Modify: `tests/test_portfolio.py`, `tests/test_autopilot.py`

**Interfaces:**
- Produces: `ProjectEngineeringService.create_from_ideas(ideas: list[ProjectIdea], market_skills: list[str]) -> tuple[str, str] | None`, returning `(task_id, proposal_id)` when new work is queued.
- Produces: `ProjectEngineeringService.handle_task(task: Task) -> TaskOutcome` for task kind `project_engineering` and `handle_revision_task(task: Task) -> TaskOutcome` for `project_revision`; main registers both plus `project_qa` on the existing single model worker.
- Produces: `ProjectManifest(runtime: Literal["python", "node", "static"], test_files: list[str], expected_behavior: list[str], source_urls: list[str])` stored with the proposal and model-generated staged files.
- Consumes: Task 1 idea repository and the shared workflow foundation (`WorkflowRepository`, `RetryableTaskError`, worker queue).

- [ ] **Step 1: Define `engineering_service`** in `tests/test_portfolio.py` from existing `client`, `app`, `db`, and `fake_planner` fixtures; instantiate a `ProjectIdea` directly in the test. Assert that an idea is selected only when its skills overlap verified target-role skill signals, every proposal has a source URL, a repeated scan creates no active duplicate, and stale/empty ideas leave the queue unchanged.

```python
def test_engineering_queues_one_original_project_from_cited_idea(engineering_service):
    idea = ProjectIdea("idea-1", "Python observability", "A small trace viewer", ["Python"], ["https://github.com/example/research"], None)
    task_id, proposal_id = engineering_service.create_from_ideas([idea], ["Python"])
    proposal = engineering_service.get(proposal_id)
    assert task_id
    assert proposal["source_urls"] == ["https://github.com/example/research"]
    assert engineering_service.create_from_ideas([idea], ["Python"]) is None
```

- [ ] **Step 2: Run the selection test and confirm the current brief-only proposal service cannot satisfy it.**

Run: `pytest tests/test_portfolio.py::test_engineering_queues_one_original_project_from_cited_idea -q`
Expected: FAIL because autonomous idea selection and source provenance are missing.

- [ ] **Step 3: Add deterministic idea scoring and an idempotent autonomous enqueue.** Rank by overlap with recurring skills from verified role listings, age, and novelty; do not use one model score as a gate. Queue at most one new project per discovery cycle and never duplicate a project with a queued, running, needs-review, approved, or quality-held state. Persist source URLs, a concise original brief, provider=`ollama`, and `cloud_confirmed=False` in the enqueue transaction.

- [ ] **Step 4: Generate a constrained project bundle.** Migration 016 adds project manifest/source fields to proposals; leave earlier migrations immutable. Ask Ollama for strict JSON with `summary`, `manifest`, and UTF-8 text files. Convert local `ProviderUnavailable` into `RetryableTaskError` without marking the proposal failed; invalid model JSON remains non-retryable. Support Python standard library, Node built-ins, or static HTML/CSS/JS only; do not include package-install commands, dependency manifests that install scripts, secrets, binaries, or shell scripts. Reuse `PortfolioPaths` traversal/symlink/size checks and cap each file at 200 KB, total bundle at 1 MB, and 30 files. Write to a fresh per-project staging path, never to `data/portfolio`.

- [ ] **Step 5: Remove per-task project instructions from the primary UI.** Replace the always-visible project-brief form with compact status for autonomous Engineering and a Needs your review list; no project input is required for work to start. Keep any legacy manual API disabled from the main office flow and never require the user to create an idea.

- [ ] **Step 6: Run portfolio and discovery tests.**

Run: `pytest tests/test_portfolio.py tests/test_autopilot.py -q`
Expected: PASS for sourced autonomous dispatch, deduplication, safe staged bundles, and no write to final portfolio before approval.

- [ ] **Step 7: Commit only this task's files.**

```bash
git add src/careeros/portfolio/service.py src/careeros/portfolio/engineering.py src/careeros/autopilot/discovery.py src/careeros/main.py src/careeros/migrations/016_project_builds.sql src/careeros/static/index.html src/careeros/static/app.js tests/test_portfolio.py tests/test_autopilot.py
git commit -m "feat: build sourced portfolio projects autonomously"
```

### Task 3: Add a fail-closed Docker sandbox for project checks

**Files:**
- Create: `src/careeros/portfolio/sandbox.py`
- Create: `src/careeros/sandbox/Dockerfile`
- Modify: `src/careeros/config.py`
- Modify: `src/careeros/cli.py`
- Modify: `README.md`
- Create: `tests/test_portfolio_sandbox.py`

**Interfaces:**
- Produces: `SandboxResult(exit_code: int | None, stdout: str, stderr: str, duration_ms: int, timed_out: bool, limit_exceeded: bool, available: bool, error: str | None)`.
- Produces: `DockerSandboxRunner(image: str, docker_executable: str = "docker")` with `check_available() -> tuple[bool, str]` and `run(project_dir: Path, manifest: ProjectManifest) -> SandboxResult`.
- Consumes: Task 2 validated staging path and manifest. No generated command strings are accepted; runner builds argv from the runtime allowlist and manifest test paths.

- [ ] **Step 1: Define `runner_without_docker` and `python_manifest()`** in `tests/test_portfolio_sandbox.py` using a fake `subprocess.run`; then assert `--network=none`, `--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, non-root `--user`, CPU/memory/pids limits, read-only `/workspace`, bounded `/tmp`, timeout handling, capped output, and that Docker-unavailable never calls a host interpreter.

```python
def test_runner_fails_closed_without_docker(tmp_path, runner_without_docker):
    result = runner_without_docker.run(tmp_path, python_manifest())
    assert result.available is False
    assert result.exit_code is None
    assert "sandbox" in result.error.lower()
```

- [ ] **Step 2: Run sandbox tests and confirm the runner is missing.**

Run: `pytest tests/test_portfolio_sandbox.py -q`
Expected: FAIL because `DockerSandboxRunner` is not implemented.

- [ ] **Step 3: Create a minimal pinned runtime image.** Base on a versioned Node 22 slim image, add Python 3 from the distribution package manager, run as UID/GID 10001, and include only `node --test` and `python3 -m unittest` runtimes. Build it with the repository's `careeros sandbox prepare` command; do not download code or dependencies while testing an individual project.

- [ ] **Step 4: Implement a narrow Docker invocation.** Use `subprocess.run(argv, shell=False, timeout=75)` with `--rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges --pids-limit=64 --cpus=1 --memory=512m --memory-swap=512m`, a read-only bind mount for `/workspace`, and a size-limited temporary filesystem. Run only fixed Python unittest discovery, fixed Node built-in tests whose manifest paths passed the safe-path validator, or static checks. Cap captured stdout and stderr at 64 KB each. Validate that every staged file is regular, non-symlink, and beneath the project root before invocation.

- [ ] **Step 5: Add `careeros sandbox check` and `careeros sandbox prepare`.** Check Docker daemon connectivity, required image presence, and an actual no-network probe; `prepare` builds the local image. The app exposes a clear offline/not-installed state, and QA stays held until `check_available()` succeeds. Never fall back to running project code on macOS.

- [ ] **Step 6: Run fake-runner tests and a controlled optional integration test.**

Run: `pytest tests/test_portfolio_sandbox.py -q`
Expected: PASS with fake Docker for all safety arguments, limits, output clipping, path attacks, unavailable daemon, and timeout. If Docker is already installed, separately run the opt-in `CAREEROS_DOCKER_INTEGRATION=1 pytest tests/test_portfolio_sandbox.py::test_real_container_has_no_network_or_host_write -q`; otherwise report unavailable and keep projects held.

- [ ] **Step 7: Commit only this task's files.**

```bash
git add src/careeros/portfolio/sandbox.py src/careeros/sandbox/Dockerfile src/careeros/config.py src/careeros/cli.py README.md tests/test_portfolio_sandbox.py
git commit -m "feat: isolate project quality checks"
```

### Task 4: Add independent Project QA, repair loops, and persistent reports

**Files:**
- Create: `src/careeros/portfolio/qa.py`
- Create: `src/careeros/migrations/017_project_qa.sql`
- Modify: `src/careeros/portfolio/service.py`
- Modify: `src/careeros/main.py`
- Modify: `src/careeros/api/portfolio.py`
- Create: `tests/test_project_qa.py`; Modify: `tests/test_portfolio.py`, `tests/test_worker.py`

**Interfaces:**
- Produces: `ProjectQAService.run_task(task: Task) -> TaskOutcome` and `enqueue(proposal_id: str, cycle: int) -> str`.
- Produces: persisted `project_qa_runs(proposal_id, cycle, status, deterministic_report_json, critique_json, provider, model, created_at)` unique by `(proposal_id,cycle)`; `status` is `passed`, `revise`, or `quality_hold`. Migration 017 creates the report table and extends the proposal status constraint through a data-preserving SQLite table rebuild; leave migrations 014–016 immutable.
- Consumes: `DockerSandboxRunner`, proposal manifest/source trail, shared task queue and handoff repository.

- [ ] **Step 1: Define `project_pipeline`** in `tests/test_project_qa.py` from existing `app`, `db`, `fake_planner`, and `client` fixtures, injecting a fake sandbox. Define `proposal_after_failed_cycles(3)` to execute three stored QA cycles and their revision tasks. Then cover passing tests plus no blockers, nonzero test plus concrete findings, Docker unavailable, timeout/limit breach, malformed reviewer JSON, repair returning to Engineering, cycle 3 failure, and idempotent re-run of a persisted QA cycle.

```python
def test_third_failed_project_qa_cycle_sets_quality_hold(project_pipeline):
    proposal_id = project_pipeline.proposal_after_failed_cycles(3)
    assert project_pipeline.latest_qa(proposal_id).status == "quality_hold"
    with pytest.raises(RuntimeError, match="quality hold"):
        project_pipeline.approve(proposal_id)
    with pytest.raises(RuntimeError, match="quality hold"):
        project_pipeline.apply(proposal_id, [])
```

- [ ] **Step 2: Run the targeted QA tests and confirm the QA service/table are absent.**

Run: `pytest tests/test_project_qa.py -q`
Expected: FAIL because independent QA results are not persisted.

- [ ] **Step 3: Implement deterministic-first QA.** Always run sandbox checks before asking the QA model to inspect source and behavior. Any unavailable sandbox, timeout, resource breach, unsafe bundle, nonzero required test, or invalid test manifest is a blocker. Convert local `ProviderUnavailable` into `RetryableTaskError` without marking the proposal failed/held; invalid model JSON remains non-retryable. Only after deterministic checks pass may the separate QA task ask the same configured local model for edge cases, inconsistent behavior, missing tests, and concrete exploit/failure ideas. Treat project files, README text, and model output as untrusted data; do not execute commands supplied by them.

- [ ] **Step 4: Implement at most three persisted repair cycles.** On blocking findings, persist the full bounded report and enqueue Engineering revision with the findings ticket; after revision, enqueue a new independent QA cycle. In the same transaction as each transition, emit `project-submitted` from worker `portfolio-engineer`/station `engineering-team-01` to `project-qa`/`project-qa-01`, `project-defect-returned` in the reverse direction, or `project-qa-passed` from Project QA to the review queue. Key events by proposal, cycle, and direction. After the third failed cycle, set `quality_hold`, retain the report, and do not create a reviewable task.

- [ ] **Step 5: Gate project approval, apply, and resume evidence.** Only `passed` QA can set proposal to `needs_review`; approval endpoint and apply method check the latest QA row transactionally. Approved files may be applied only after the user selects replacement paths. Resume evidence export must read only approved/applied project metadata and must not assert usage/impact the user has not confirmed.

- [ ] **Step 6: Run QA/portfolio/worker tests.**

Run: `pytest tests/test_project_qa.py tests/test_portfolio.py tests/test_worker.py -q`
Expected: PASS for deterministic and model QA, 3-cycle hold, report persistence, no final writes before user approval, and exact handoff event history.

- [ ] **Step 7: Commit only this task's files.**

```bash
git add src/careeros/portfolio/qa.py src/careeros/migrations/017_project_qa.sql src/careeros/portfolio/service.py src/careeros/main.py src/careeros/api/portfolio.py tests/test_project_qa.py tests/test_portfolio.py tests/test_worker.py
git commit -m "feat: review portfolio projects with independent QA"
```

### Task 5: Represent Engineering and Project QA in the office and release both pipelines

**Files:**
- Modify: `src/careeros/api/workspace.py`
- Modify: `src/careeros/static/index.html`
- Modify: `src/careeros/static/app.js`
- Modify: `src/careeros/static/office-layout.js`
- Modify: `src/careeros/static/office-renderer.js`
- Modify: `src/careeros/static/office.css`
- Modify: `README.md`
- Modify: `tests/test_workspace_api.py`, `tests/office-renderer.test.mjs`; Create: `tests/test_portfolio_api.py`

**Interfaces:**
- Produces: worker IDs `portfolio-engineer` and `project-qa`, with QA appearance explicitly configured as a distinct male pixel worker at station `project-qa-01`.
- Produces: worker tooltip fields `department`, `model`, `model_status`, `task_label`, `status`, `latest_result`, and `hold_reason` for Project QA.
- Consumes: persisted QA/provenance/handoff rows from Tasks 1–4 and Hiring Manager worker schema from the hiring plan.

- [ ] **Step 1: Write workspace and renderer contract tests.** Assert Project QA is always listed in the first release, reflects local model/sandbox offline states, displays hold reasons, and its three handoff event types map to project/pass/defect items.

```python
def test_workspace_shows_active_project_qa_worker(client):
    worker = next(row for row in client.get("/api/workspace").json()["workers"] if row["id"] == "project-qa")
    assert worker["department"] == "Project QA"
    assert worker["character"] == "male"
    assert worker["status"] in {"waiting", "working", "quality_hold"}
```

- [ ] **Step 2: Run the UI/API contract tests and confirm the QA worker is absent.**

Run: `pytest tests/test_workspace_api.py::test_workspace_shows_active_project_qa_worker -q && node --test tests/office-renderer.test.mjs`
Expected: FAIL because the worker is not in the workspace projection or sprite registry.

- [ ] **Step 3: Add the Project QA worker and visible station.** Add male character appearance `project-qa` and `hiring-manager` (if the hiring plan's UI task has not already added it) and API field `character: "male"` for both; use compact silhouette dimensions, bright foreground contrast, QA workstation props, and station IDs aligned with persisted handoffs. Keep the office full-screen and integrated side panels; do not add a separate dashboard or skyline.

- [ ] **Step 4: Connect persisted project handoffs to worker motion.** Engineering walks to QA while a project artifact moves between stations; defect return sends a ticket to Engineering and returns that actor to revision; pass uses a green result item and makes the QA worker idle. Polling/reload must not replay old interactions; every interaction carries the persisted event ID.

- [ ] **Step 5: Update review panels and setup.** Show the source idea links, project summary, staged file diff, reproducible QA report, resolved/unresolved findings, local model state, and sandbox availability. Make QA-passed projects part of Needs your review. Remove user-created briefs from the primary flow. Compact setup explains that Docker is required to execute QA checks and that absent isolation holds projects safely.

- [ ] **Step 6: Run release tests and verify both active pipelines together.**

Run: `pytest tests/test_project_sources.py tests/test_portfolio.py tests/test_project_qa.py tests/test_workspace_api.py tests/test_portfolio_api.py -q && node --test tests/office-renderer.test.mjs`
Expected: PASS for both male QA workers, accessible review actions, source trace, sandbox state, and event-driven character interactions.

- [ ] **Step 7: Commit only this task's files.**

```bash
git add src/careeros/api/workspace.py src/careeros/static/index.html src/careeros/static/app.js src/careeros/static/office-layout.js src/careeros/static/office-renderer.js src/careeros/static/office.css README.md tests/test_workspace_api.py tests/office-renderer.test.mjs tests/test_portfolio_api.py
git commit -m "feat: show active project QA in the office"
```

### Task 6: Verify both autonomous pipelines and first-run setup

**Files:**
- Create: `tests/test_autonomous_workflows_e2e.py`
- Modify: `README.md`, `src/careeros/static/index.html`, `src/careeros/static/app.js`

**Interfaces:** The single one-time profile setup remains resume, target roles, acceptable locations, and optional eligibility facts; no daily job, resume, or project prompt is required. The workflow starts from persisted setup, not a user-issued task.

- [ ] **Step 1: Write a mocked end-to-end test** that performs one scheduled discovery with a qualified and a held role, creates one sourced project, runs critique/revision on one application, runs a project defect/repair/pass cycle through a fake sandbox, and verifies final review queues for both. Assert no project idea input, no application submission request, no X calls, no cloud requests, and no portfolio file apply before approval.
- [ ] **Step 2: Run the integration test.**

Run: `pytest tests/test_autonomous_workflows_e2e.py -q`
Expected: PASS with temporary SQLite, fake planners, fake Docker, and `httpx.MockTransport` only.

- [ ] **Step 3: Finish the setup guide.** Document Python setup, Ollama/model setup, optional Docker image preparation, data location, what runs every six hours, what stops when the Mac sleeps, how to read quality holds, and the two separate human approval actions.
- [ ] **Step 4: Run all workflow tests and inspect the release diff.**

Run: `pytest tests/test_autonomous_workflows_e2e.py tests/test_hiring_workflow_e2e.py tests/test_project_sources.py tests/test_project_qa.py tests/test_hiring_manager.py -q && node --test tests/*.test.mjs`
Expected: PASS with no live provider/job source/Docker use unless the explicitly gated Docker integration test is invoked; no approval or package route can bypass its pipeline gate.

- [ ] **Step 5: Commit only this task's files.**

```bash
git add tests/test_autonomous_workflows_e2e.py README.md src/careeros/static/index.html src/careeros/static/app.js
git commit -m "test: verify autonomous hiring and project workflows"
```
