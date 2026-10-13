# CareerOS Job Intake and Verification Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make automatic U.S. job intake resilient and explainable while preserving public-source-only access, hard application gates, local-first processing, and final user approval.

**Architecture:** Keep existing source adapters and discovery flow. Enrich normalized job records with provenance, resolve public redirects through a bounded, DNS-validated HTTP layer, and return typed verification outcomes with structured evidence. Persist outcomes through a forward SQLite migration. Process and retry listings independently with bounded retry state, then expose outcome details in API/UI and the worker summary. Never let verification invoke an LLM or bypass access controls.

**Tech Stack:** Python, FastAPI, SQLite migrations, HTTPX, existing React-free static UI, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-10-13-careeros-job-intake-verification-design.md`

## Global Constraints

- Preserve existing user changes in the working tree; edit only files required by this plan and inspect diffs before each commit.
- Write a failing test before each behavior change, run the focused test, implement the smallest change, then run the focused test again.
- All network, DNS, source, and planner behavior in tests must be mocked. No external job-board requests in tests.
- Never use browser identity spoofing, credentialed requests, CAPTCHA handling, or access-control bypasses.
- Reject non-public DNS answers on every redirect hop; pin the actual connection to a validated public IP while retaining original hostname validation and TLS SNI.
- Preserve `verified`/`held` gate compatibility. A typed outcome must never weaken a hard application gate.
- Do not submit applications or send resume data to employers. Preserve explicit opt-in and confirmation for OpenAI use; never add automatic paid fallback.
- Retry only transient outcomes, with a strict attempt cap and idempotent state updates. A source/listing failure must not stop unrelated listings.

## Task 1: Add typed verification outcomes and safe redirect resolution

**Files:** `src/careeros/jobs/verification.py`, `src/careeros/jobs/models.py`, `tests/test_job_verification.py`

- [ ] **1.1 Add failing tests for outcome model and redirect policy.** Extend `tests/test_job_verification.py` to cover typed result fields and these cases: relative redirect, absolute public redirect, exactly five redirects, redirect loop, sixth redirect, HTTPS downgrade, credentials in URL, non-HTTP scheme, and DNS answers containing loopback/private/reserved addresses. Mock HTTP transport and resolver.
- [ ] Run `rtk pytest -q tests/test_job_verification.py` and confirm the new cases fail for the expected reasons.
- [ ] **1.2 Implement backward-compatible result types.** Add an outcome enum/literal for `verified`, `closed`, `identity_mismatch`, `insufficient_detail`, `access_restricted`, `not_found`, `transient_error`, and `unsafe_destination`. Extend `VerificationResult` with outcome, checked URL, final URL, timestamp, evidence summary, and fingerprint fields while preserving existing `verified` and `reason` accessors.
- [ ] **1.3 Implement manual safe redirect resolution.** Keep automatic redirect following disabled. Resolve relative `Location` against the current URL, validate each URL and DNS answer before each request, reject HTTPS downgrade and unsafe addresses, pin the connection to a validated IP without changing Host/SNI, detect loops, and stop after five redirects. Apply existing timeout/body-size limits at every hop.
- [ ] **1.4 Classify HTTP and transport failures.** Map 403 to `access_restricted`, 404/410 to `not_found`, 429 and 5xx/timeouts/temporary network errors to `transient_error`, unsafe URL/DNS/redirect cases to `unsafe_destination`, and preserve existing boolean gate semantics.
- [ ] Run `rtk pytest -q tests/test_job_verification.py`; all new and existing verification tests must pass.

## Task 2: Extract primary posting evidence and preserve source identity

**Files:** `src/careeros/jobs/verification.py`, `src/careeros/jobs/models.py`, `src/careeros/jobs/boards.py`, `src/careeros/jobs/speedyapply.py`, `src/careeros/jobs/arbeitnow.py`, `tests/test_job_verification.py`, `tests/test_job_sources.py`.

- [ ] **2.1 Add failing structured-evidence and adapter tests.** Cover JSON-LD `JobPosting` title, hiring organization, description, identifier, and employment/location fields; malformed/multiple JSON-LD blocks; primary posting versus related-job cards; common punctuation/company-suffix variants; genuine title/company mismatch; and distinct source, employer, and application URLs with requisition ID and publication/fetch timestamps.
- [ ] Run the focused verification and adapter tests and confirm the new expectations fail.
- [ ] **2.2 Parse structured evidence first.** Extract the primary `JobPosting` from JSON-LD, avoiding related postings and navigation content. Fall back to visible primary-page text only when structured data is absent or incomplete. Record which evidence source supported the result.
- [ ] **2.3 Normalize identity conservatively.** Normalize case, whitespace, punctuation, and common legal suffix formatting. Permit only equivalent title/company representations when positive primary-posting evidence remains. Do not use related-job text or a loose substring match as proof.
- [ ] **2.4 Preserve URL provenance in adapters.** Extend the normalized job record and existing adapters with separate source listing URL, employer/ATS posting URL, and application URL; preserve requisition IDs and available source publication/update times, plus CareerOS fetch time. For SpeedyApply, do not copy an aggregator clickthrough into the employer URL unless its destination has actually been resolved and validated.
- [ ] Run all verification and adapter tests; confirm existing source fixtures remain compatible.

## Task 3: Persist typed outcomes and bounded per-listing retry state

**Files:** `src/careeros/migrations/018_job_verification_outcomes.sql`, `src/careeros/jobs/repository.py`, `src/careeros/jobs/models.py`, `src/careeros/autopilot/discovery.py`, `src/careeros/api/jobs.py`, `tests/test_job_verification.py`, `tests/test_autopilot.py`, `tests/test_jobs_api.py`

- [ ] **3.1 Add migration and repository tests first.** Test upgrading a database containing existing jobs and verification rows without data loss; persist/read every outcome, reason, checked/final URL, checked timestamp, evidence fingerprint, attempt count, and next retry time. Test repeated writes are idempotent.
- [ ] Run focused migration/repository tests and confirm they fail before implementation.
- [ ] **3.2 Add forward-only migration.** Add migration `018_job_verification_outcomes.sql` after the existing migration 017. Add nullable outcome/evidence fields and retry metadata while retaining the existing status column and its `verified`/`held` values. Do not reset or recreate the database.
- [ ] **3.3 Extend repository interfaces.** Add typed save/read methods for verification outcomes and retry scheduling. Keep existing callers working through compatible defaults or adapters.
- [ ] **3.4 Make discovery isolate each listing.** Catch and persist expected per-listing verification failures; continue processing remaining listings. Persist transient retry scheduling with a small fixed cap and bounded backoff. Do not rerun completed planning or drafting work when only verification is retried. Do not retry permanent or unsafe outcomes.
- [ ] **3.5 Make manual recheck use the same path.** Extend the existing `POST /api/jobs/{job_id}/verify` flow to persist typed results and retry metadata. Repeated checks must not create duplicate applications or invoke any planner.
- [ ] Run `rtk pytest -q tests/test_job_verification.py tests/test_autopilot.py tests/test_jobs_api.py`.

## Task 4: Surface outcomes and scan recovery in the UI

**Files:** `src/careeros/api/jobs.py`, `src/careeros/static/app.js`, `src/careeros/static/index.html`, `src/careeros/static/styles.css`, `tests/test_jobs_api.py`, `tests/office-renderer.test.mjs`

- [ ] **4.1 Add failing API/UI tests.** Verify job payloads include outcome, plain-language reason, checked time, safe retry eligibility, and source provenance. Verify cards distinguish inaccessible, closed, mismatched, insufficient-detail, transient, and unsafe outcomes. Verify retry appears only when allowed and only for confirmed U.S. roles.
- [ ] Run focused tests and confirm they fail before implementation.
- [ ] **4.2 Implement status visibility.** Extend job payloads and cards to show concise outcome and reason, last checked time, and source/employer link provenance where safe. Keep the existing US-only control and hard gate display.
- [ ] **4.3 Add retry affordance.** Reuse the existing manual recheck control for safe/retryable outcomes; disable it while in flight and render the returned typed outcome without duplicating the job or application.
- [ ] **4.4 Add per-scan summary.** Extend the existing Job Hunter worker status/summary with counts for verified jobs, held outcomes by class, transient retries scheduled, and source failures. If no durable summary model exists, use the current worker event/status mechanism rather than adding an unrelated queue subsystem.
- [ ] Run `rtk pytest -q tests/test_jobs_api.py` and `rtk proxy node --test tests/office-renderer.test.mjs`.

## Task 5: Verify the complete mocked workflow and update setup guidance

**Files:** `tests/test_hiring_workflow_e2e.py`, `tests/test_autopilot.py`, `tests/conftest.py`, `README.md`

- [ ] **5.1 Add failing end-to-end regression cases.** Mock sources, DNS, HTTP, and planner. Cover mixed batches containing a verified listing, 403, stale 404, transient 503, unsafe redirect, and identity mismatch. Assert the verified listing reaches Hiring Manager review; failures remain visible; transient attempts are bounded; one failure does not block another; no duplicate application is created; and no external submission or paid fallback occurs.
- [ ] Run `rtk pytest -q tests/test_hiring_workflow_e2e.py tests/test_autopilot.py` and confirm new regression cases fail before implementation.
- [ ] **5.2 Implement only integration fixes required by those tests.** Keep the workflow independent per listing and preserve every existing deterministic gate and final approval step.
- [ ] **5.3 Update operator guidance.** In `README.md`, explain outcome meanings, safe retry behavior, public-source limitations, and where to see Job Hunter scan counts. Document that 403 means access restricted, not fake/closed, and is not bypassed.
- [ ] **5.4 Run full regression.** Run `rtk pytest -q` and `rtk proxy node --test tests/office-renderer.test.mjs`; inspect migrations against a copy of the existing schema and inspect `rtk proxy git diff --check`.

## Review Focus

- Redirect handling validates and pins every hop, preserves TLS hostname verification, and rejects mixed public/private DNS answers.
- Identity checks rely on the primary posting and structured evidence where available; permissive parsing must not create false positives.
- The existing `verified`/`held` application gates remain authoritative, with every outcome other than `verified` held.
- Retries are bounded, per listing, idempotent, and do not repeat planner work or invoke a paid model.
- Source, employer, and application URLs remain distinct and visible enough to explain provenance.
- Job failures remain recoverable and understandable without weakening U.S. eligibility, Hiring Manager review, or user approval.
- No tests contact real job boards or employer sites, and no code attempts to evade access restrictions.

---

## Execution Handoff

Execute this plan using the subagent-driven development workflow selected by the user earlier in the CareerOS project. Work in small task slices, keep changes isolated by file ownership, review each completed slice, run its listed tests, and preserve all pre-existing uncommitted user changes. Do not begin implementation until the user has reviewed and approved this plan.
