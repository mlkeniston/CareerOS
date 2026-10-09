# CareerOS Office Autopilot Design

**Date:** 2026-10-09  
**Status:** Approved
**Supersedes:** The home-screen and user-triggered workflow portions of `2026-10-09-careeros-mvp-design.md`  
**Target:** Existing local-first CareerOS MVP on a 2020 M1 Mac with 8 GB RAM

## User goal and agreed behavior

CareerOS should visibly work toward a technology internship or job without asking the user to invent tasks or start each work cycle. On launch it begins public job discovery, continues on a schedule, and shows its workers doing real queued work in a pixel-art office. Personal application preparation starts automatically when a resume is available. Missing personal information must not block general job discovery or the rest of the app.

Application packets remain drafts. A person must review and approve each packet before any external application submission; CareerOS does not submit applications in this MVP. Portfolio changes remain proposals until a person reviews and applies them. These boundaries carry forward from the earlier approved MVP design.

Ollama stays the default and the only planner available to unattended work. OpenAI remains optional and is used only for a foreground task after the user reviews the exact data and confirms paid use. No provider fallback or unattended paid request is allowed. Existing FastAPI, SQLite, job connectors, persistent queue, profile, application, portfolio, and setup foundations are retained where they serve this workflow.

## Video reference analysis

The supplied 2:36 recording shows the office interface at the beginning and again near 2:10. Much of the middle shows a separate model-ranking page; that page is not part of the target office UI.

The reference depicts connected station rooms floating in a starfield, with gridded floors, metallic walls, corridors, hazard-marked doorways, named workstations, and pixel workers. The approved CareerOS treatment uses an angled isometric map with worn concrete and steel, dusty Fallout-era texture, and restrained neon cyan, green, amber, purple, and coral state lights. The office fills the first screen; the worker roster and details open on demand.

The map communicates presence and location; the roster communicates identity and current activity; station labels and counters communicate work and output. The recording is handheld and soft, so exact station names, counts, and animation states are not treated as requirements.

## Approaches considered

1. **Redraw the current static SVG illustration.** It would be quick and preserve the current no-build setup, but it would leave the main mismatch in place: workers and activity would still be decorative rather than tied to task state.
2. **A small Canvas renderer with an HTML control shell (recommended).** A data-driven tile map and block-built sprite renderer can draw the station, animated workers, and status lights at pixel scale. A normal HTML roster, navigation, and task inspector remain keyboard-accessible. This adds no frontend runtime or build dependency and fits the existing Python-served app.
3. **Phaser or another game framework.** This provides mature tile maps and animation tools, but adds a Node build and runtime dependency for a single-user status view. It can be reconsidered if the lightweight renderer proves too limited.

## Design

### 1. The office is the home screen

Replace the cream card layout and static cozy studio drawing with a dark, full-window operations view inspired by the reference. A dominant Canvas map depicts six connected room footprints for Jobs, Resume, Applications, Engineering, LinkedIn Outreach, and Dispatch. Use an angled isometric camera, diamond floor tiles, raised worn-steel and concrete walls, scratched surfaces, cables, equipment, hazard marks, and small signs. Pixel workers use a finer sprite grid for readable face, uniform, and team details. Neon status accents retain the established cyan, green, amber, purple, and coral palette.

The four rooms represent Job Hunters, Resume Team, Application Team, and Engineering Team. A small manager/dispatch station coordinates their queue. Each room has several named stations so a user can see both the team's purpose and where a task is assigned. A compact bottom strip shows live counts such as jobs found, work completed, drafts awaiting review, and the current local model state.

Keep job search, application review, resume editing, portfolio proposals, and settings as reachable station views. Selecting a worker or desk opens a compact HTML task inspector with its task, status, result or error, and relevant next action. Keyboard-accessible roster buttons provide the same selection path as clicking a sprite or room. Dragging horizontally orbits the isometric camera through a full turn; the room geometry, station positions, worker positions, and hit areas reproject together and auto-fit the canvas. A reset control restores the initial view.

### 2. Pixel workers reflect real queue state

Workers are small, block-built pixel characters with distinct colors. The map renderer animates idle, walking, and working poses. A worker walks along a corridor when assigned to a different station, then works beside a corresponding desk or terminal while its task is actually running. The left roster uses the same worker identity, color, and state.

Backend task state is authoritative. `queued` work appears as waiting/assigned, `running` work appears as working with elapsed time, `needs_review` appears at a review station, `completed` contributes to shipped totals, and failures or missing prerequisites have a visible honest state. Idle or blocked workers do not appear to be producing results. Since the local MVP uses one queue worker to protect the 8 GB machine, the UI may show one active task and other workers waiting; it must not imply concurrent execution that did not happen. Reduced-motion and keyboard paths remain available.

### 3. Autopilot starts useful work without a task prompt

The app schedules an initial public job-board refresh after startup and repeats it every six hours. Scheduling state is persisted so restarts do not create duplicate first-run scans. It uses the already configured public sources, stores results in SQLite, and classifies broad technology internship and entry-level listings locally. Refresh uses public listings and search filters only; no resume or profile data is sent to job sources. Cached jobs remain searchable if a source is unavailable. Autopilot can be paused and resumed from the office; it is enabled by default.

When a resume and target information exist, local matching can queue application-preparation drafts for suitable discovered roles without asking the user to start each task. Without that material, general discovery still runs and the Resume and Application workers show that personal materials are unavailable; CareerOS must not invent the user's experience. Application work creates a reviewable local draft only.

The Engineering worker can use recurring skills in discovered listings to queue one local-only portfolio proposal at a time. It stores proposed files in the existing staging area. A person must review and apply a proposal; generated code is never run. Avoid repeated proposals for the same skill pattern. If Ollama is unavailable, non-AI job discovery continues, and AI-dependent work waits or reports a clear local-model status.

Unattended tasks always use the local planner, never OpenAI. An explicit OpenAI choice for an individual foreground task retains the existing data preview and paid-use confirmation. Selecting or configuring OpenAI does not change autopilot behavior.

### 4. Backend and UI data flow

Retain FastAPI, SQLite, the existing task queue, and the current domain services. Add a scheduler that inserts idempotent discovery work into the persistent queue, plus handlers for discovery and any safely bounded market-driven portfolio proposals. Expose a read-only workspace snapshot API containing department/worker identity, assigned station, queue-derived status and elapsed time, recent real tasks, activity counts, model readiness, and autopilot state. Add a pause/resume control that changes the persisted scheduler setting.

The Canvas renders static room/station definitions and live worker positions from the workspace snapshot. Camera rotation reprojects map geometry and interactive targets from their grid coordinates. The HTML shell renders the roster and task inspector from the same response. Poll the snapshot at a modest interval; animate movement locally between server-provided states. The renderer must not fabricate task completion or metrics.

## Acceptance criteria

- The first screen after launch is a dark, richly detailed isometric pixel office, not a form or a static illustration card.
- The office has six labeled work areas, connected rooms/corridors, on-demand worker details, per-station activity, and a compact neon interface.
- Dragging the office orbits through a full 360-degree turn while keeping room geometry, workers, and clickable stations aligned; reset returns to the initial camera view.
- Pixel characters visibly work or wait at stations. Their state and counters agree with real queue records and do not claim that queued work is running.
- First-run discovery starts without a manually entered task; scheduled scans persist across restarts and do not duplicate.
- Public job discovery works without a resume, profile, Ollama, OpenAI key, or job-board credentials. Personalization becomes more specific when the user has supplied relevant materials, without blocking initial use.
- Local AI tasks use Ollama. Autopilot never calls OpenAI. A foreground paid call requires the existing explicit confirmation and never falls back automatically.
- Application drafts and portfolio proposals remain reviewable; external submission, generated-code execution, and unapproved portfolio writes remain unavailable.
- Workers, rooms, and inspectors are navigable with a keyboard. Reduced-motion preference is respected.
- Automated tests cover scheduler idempotency/restart behavior, job discovery failure with cache retention, queue-to-worker UI state mapping, pause/resume, the no-cloud-autopilot invariant, and existing application/portfolio approval boundaries.
- The README explains that first-run discovery begins automatically, how to pause it, how Ollama affects AI-dependent work, and how to provide optional personal materials later.

## Explicit exclusions

This change does not add paid job-board access, scrape login-protected sites, sign into employer sites, submit applications, send messages, execute proposed portfolio code, add cloud sync, or add a frontend framework/build step. The main scene is a compact operations simulation, not a real-time game with unrelated physics or combat mechanics.

## Existing implementation facts

The repository already has the local database and queue, Ollama/OpenAI adapters, public job connectors, application packet review/export, portfolio proposal staging, a static one-worker SVG illustration, and manual job refresh. The worker currently registers only application and portfolio handlers. This design therefore calls for extending the current system and replacing its home scene, not recreating the backend foundation.
