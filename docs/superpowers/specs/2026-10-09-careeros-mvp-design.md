# CareerOS MVP Design

**Date:** 2026-10-09  
**Status:** Awaiting user review  
**Target:** Local-first open-source job-search and portfolio assistant for a 2020 M1 Mac with 8 GB RAM

## Goal

CareerOS helps one person find technology internships and jobs, prepare application materials, and make portfolio progress from one local app. A useful first run should let the user save resume text, discover and search listings, save a role, create an application draft, review and approve that draft, and export it. A separate portfolio worker should turn a project brief into proposed files that the user can inspect and apply.

The app stores its working data locally. Ollama is the default planner. The optional OpenAI planner is GPT-6 Luna (`gpt-6-luna`), accessed only when the user selects the cloud provider and explicitly launches a task with a paid-use confirmation. OpenAI's official model documentation lists standard rates of $0.10 per million input tokens and $0.50 per million output tokens; the model is not available on the API free tier. These rates are documented as of this design date and can change. The app never switches providers automatically.

## Approaches considered

1. **FastAPI, SQLite, and a lightweight browser UI (recommended):** FastAPI serves the API and static JavaScript modules; a small SVG/CSS office supplies the top-down pixel-art navigation. This keeps installation to Python plus Ollama and avoids a separate frontend build.
2. **FastAPI plus React/Vite:** Gives a component framework for a larger UI, with Node and a build step to install and maintain.
3. **Packaged desktop shell:** Could feel more native, but adds packaging, memory use, and platform-specific work before the core workflow is proven.

Option 1 best fits local-first use on an 8 GB Mac while leaving the interface easy to replace later.

## Architecture

- One Python process runs FastAPI on `127.0.0.1` by default and serves the browser UI. It is a single-user local app, not a hosted service.
- SQLite stores profiles, resumes, listings, applications, task records, approval state, and provider preferences. Job search uses SQLite FTS5 when available, with a regular SQL search fallback.
- A persistent task table acts as the local queue. A small worker claims queued work atomically, records progress and results, and recovers work left running after a restart. Queue work is limited to one worker process for the MVP.
- Provider adapters expose one planner interface. The Ollama adapter calls the local Ollama HTTP API. The OpenAI adapter calls the OpenAI Responses API and remains disabled until configured with an API key.
- The UI is static JavaScript, HTML, SVG, and CSS served by FastAPI. The office map has clickable stations for the job board, resume/application desk, portfolio workshop, and planner settings. It remains navigable through normal buttons and keyboard controls.
- App-owned generated files live below the configured data directory in a `portfolio/` folder. The app does not execute generated code or submit applications.

## Main workflows

### Find a job

The user searches cached listings by role, company, location, internship/early-career type, or keywords. A user-triggered refresh fetches a public, no-key job source through a replaceable connector and saves the results in SQLite. The first implementation will include the Arbeitnow public job-board feed plus configurable public Greenhouse/Lever employer-board feeds, a fixture set for offline setup and tests, and a manual-add form so the workflow still works if a feed is unavailable. Refresh failures leave the existing cache searchable. Feed requests include only search filters, never a resume or profile.

### Prepare an application

The user creates or imports plain-text resume versions, saves a listing, and asks the selected planner to prepare a tailored application packet. The packet contains a draft cover letter, resume-alignment notes, and editable answers or next steps. The task enters `needs_review`; nothing is sent to an employer. The user may edit, approve, and export the packet as Markdown or plain text. Approval authorizes the local export only.

### Engineer a portfolio project

The user submits a project brief and, optionally, an existing project directory inside CareerOS's managed portfolio area. The worker creates a plan and proposed file changes in a staging area. The UI shows the proposed paths and contents before the user applies them. Applying writes only under the managed portfolio directory. The MVP does not run shell commands, install packages, publish work, or write to arbitrary paths.

### Choose a planner

Ollama is selected by default with a configurable small model (initial default: `qwen2.5:1.5b`). Selecting OpenAI does not itself make a request. For each cloud-backed task, the user sees a notice that the included resume/profile and job or project text will be sent to OpenAI and that the call may incur API charges, then explicitly confirms that task. If Ollama is unreachable, CareerOS reports the failure and offers a local retry; it never falls back to OpenAI. If the OpenAI key is absent, the cloud option is unavailable.

## Data and service boundaries

The core records are:

- `profiles` and `resumes`: user-authored local career information and resume versions.
- `jobs`: normalized listing data, source, source URL, and fetched/updated timestamps; indexed for local text search.
- `applications`: a saved job's editable prep packet and its review/export state.
- `tasks`: persistent queue type, input references, status, timestamps, and sanitized error detail.
- `portfolio_proposals`: generated plan/files, review status, and applied destination under the managed directory.
- `settings`: selected provider and non-secret preferences. API keys come from environment variables and are never stored in SQLite or returned by the settings API.

The API separates listing search/refresh, profile and resume management, application preparation/review/export, portfolio proposal/review/apply, task status, and provider settings. Provider calls receive only the data needed for the active task. Secrets and full resume contents are excluded from application logs.

## Approval and privacy controls

- No account or cloud sync is part of the MVP.
- The server binds to loopback unless the user changes configuration deliberately.
- Local is the default provider. Provider selection is visible and persisted locally.
- A cloud call requires an explicit per-task action and paid-use confirmation. No background cloud planning, fallback, hidden provider change, or automatic retry of a cloud request is allowed.
- Job listing refresh transmits search filters only.
- Application drafts require human review. CareerOS does not apply, email, or contact employers.
- Portfolio changes require review before they are copied from staging into the managed project folder. Generated programs are not executed by the worker.
- Export and apply actions display the destination before writing.

## Failure behavior

- A job-source timeout or malformed response is shown as a refresh error; cached listings remain available.
- A provider timeout, missing model, or invalid credentials marks the task failed with a concise actionable message. Retrying is user-initiated, and a failed provider never triggers a different provider.
- A worker restart returns abandoned local tasks to the queue if they have no saved result and are safe to retry. An interrupted cloud task is marked `interrupted` and waits for a new user action with paid-use confirmation, since the prior request may already have incurred usage. Tasks with results retain them for review rather than running again.
- SQLite writes use transactions. Search and read-only views remain usable when a background task fails.
- Invalid or unsupported proposed paths are rejected before applying portfolio files.

## Testing and acceptance

Automated tests will use a temporary SQLite database, fake planner adapters, and mocked job feeds; tests will not call paid APIs or depend on live job sites. The suite covers:

- API flows for creating a resume, refreshing/searching jobs, saving a role, preparing a packet, editing it, approving it, and exporting it.
- Queue persistence, atomic claiming, failure reporting, and restart recovery.
- The Ollama default, provider switching, and the invariant that provider failures never invoke a second provider.
- Cloud confirmation enforcement and secret redaction.
- Portfolio staging, review, apply-path restrictions, and prevention of execution.
- Static UI delivery and an end-to-end workflow with fake providers.

The setup guide will cover Python environment creation, installing dependencies, installing/running Ollama, pulling the configured small model, starting CareerOS, configuring an optional OpenAI API key, and running the tests. The application is considered ready when the complete local workflow works without an API key, survives restart with its SQLite data and queue intact, and all tests pass without network access.

## MVP exclusions

The first release will not auto-submit job applications, send email, scrape login-protected job sites, sync user data to a cloud account, run generated code, publish a portfolio, or support multiple accounts. It will not require React, Phaser, Docker, or a paid job-board API.

## Open implementation assumptions

- MIT is the proposed source license unless the user names a different one.
- The initial aggregate source is the public Arbeitnow job-board feed; Greenhouse/Lever integrations use public employer-board listings where the user supplies a board identifier. Source connectors can be replaced without changing the API or database contract.
- Resume input is plain text (`.txt`/Markdown or paste) in the MVP. PDF/DOCX parsing is deferred to keep local setup and memory use small.
- The local model is configurable; the proposed `qwen2.5:1.5b` tag is a starting point, not a quality guarantee on every machine.
