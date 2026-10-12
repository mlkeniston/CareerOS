# CareerOS Autonomous Hiring Pipeline Design

**Status:** Conversational design approved; written spec awaiting user review
**Date:** 2026-10-11
**Scope:** Hiring workflow first; engineering and project QA are a later phase

## Goal

CareerOS should independently find relevant technology internships and jobs, prepare truthful application materials, run them through a deliberately skeptical hiring review, and present only verified, quality-cleared packages for the user's decision. The user should not have to assign daily tasks or provide project ideas. After a one-time setup with a resume, target roles, and acceptable locations, the departments work from persistent queues. The user remains the final approver and submits every application themselves.

The intended user is running CareerOS locally on a 2020 M1 Mac with 8 GB of unified memory. The interface should remain the established full-screen, isometric neon pixel-art office, with integrated side panels and minimal explanatory text.

## Decisions

- Implement the hiring pipeline as the first delivery phase. Design the later engineering and project-QA path now, but do not include it in the first release.
- Extend CareerOS's existing FastAPI, SQLite, persistent queue, scheduler, planner gateway, job sources, application service, and office UI. Keep the workflow inside the current application rather than adding a distributed agent framework.
- Departments act autonomously from saved profile data and queued work; the user does not assign each task.
- Local Ollama is the default and the only provider used for unattended work. Use the configured small local model, currently `qwen2.5:1.5b`, and process one model task at a time.
- OpenAI is optional and explicitly selected for a user-started task. Its documented API model ID is `gpt-6-luna`. Before every cloud request, disclose the data that will be sent and require paid-use confirmation. Record provider and usage metadata. Do not automatically fall back to a cloud provider or silently retry a failed paid request. OpenAI API usage is token-billed; it is separate from a ChatGPT plan. See the [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna) and [pricing page](https://developers.openai.com/api/docs/pricing) for current details.
- Approval creates a local application package for the user to submit. CareerOS never submits applications, logs into employer portals, or sends outreach.
- Treat source listings, resume text, profile fields, and model output as untrusted data. Do not follow instructions embedded in source content.
- Do not bypass website access controls, authentication, rate limits, or published API restrictions.

## Existing foundations and gaps

The repository already includes a six-hour autopilot scheduler, a restart-recoverable SQLite queue, public job sources (Arbeitnow and configurable Greenhouse/Lever boards), role/location filtering, automatic local application drafting, approval-gated Markdown export, a provider gateway with per-task cloud confirmation, and a worker-status office API. The default app binds to loopback. These are foundations to extend.

The main gaps for this design are employer-source verification and eligibility gates, evidence-linked resume tailoring, an adversarial Hiring Manager review with bounded revision cycles, an assembled application package, and office state that reflects the added review stage. Current automatic discovery also selects a single high-scoring role and can queue other department work; the hiring phase should select and deduplicate opportunities according to the pipeline below.

## Phase 1: Hiring workflow

### 1. Discovery and verification

Add the user's requested [SpeedyApply 2027 SWE College Jobs](https://github.com/speedyapply/2027-SWE-College-Jobs) listing source alongside existing public feeds. Parse it as a discovery index, not as proof that a job remains open. Keep each record's source URL, employer application URL, source update or posting date when available, and retrieval time.

For a candidate role, verify that its employer application page is reachable and still describes the same role. A missing, redirected, stale, inconsistent, or otherwise uncertain employer listing is held with a concrete reason; it is not sent to resume preparation as a ready opportunity. Keep third-party listing text separate from employer-provided text. Deduplicate using a stable employer/role/location/application-URL identity, with database constraints or transactional checks so repeat scans do not create duplicate applications.

Recheck the employer posting immediately before offering the package for final human review. If it has closed or changed materially since preparation, invalidate the ready state and return it to verification/hold rather than presenting stale materials.

Discovery sources must be public and accessed through a supported feed, repository, or official endpoint. Feed failures should not erase cached roles. The existing six-hour cadence may remain the default while CareerOS is running. The Mac must be awake and the app running for scans; queued state survives close/restart and resumes later.

### 2. Fit and eligibility gates

Use the saved target roles and locations. A role may proceed only when:

1. The current employer posting is verified.
2. The role matches the user's saved role and location preferences.
3. The posting provides enough detail to prepare a truthful package.
4. Any material eligibility requirement can be established from the saved profile. If eligibility is absent or unclear, hold the job and show what is unknown instead of assuming.

Use independent gate results with reasons, not one aggregate AI score that can override a failed gate. Listings that fail fit may remain searchable in the local job cache but do not enter the application-preparation queue.

### 3. Resume and application preparation

Preserve the original resume. Create a separate per-job draft that may reorder or rephrase supported experience and emphasize relevant keywords, but may not add skills, credentials, dates, impact, or experience that are not evidenced in the user's saved resume/profile or an already completed and approved portfolio project.

Store a trace for each material claim in the tailored resume and application answers, pointing to the supporting profile/resume evidence. Unsupported claims are validation failures, not items for the user to discover after approval. Include the verified employer link and job facts used to prepare the draft. Generate the cover letter and application-answer drafts from this same fixed job/profile/resume snapshot so all materials stay consistent.

### 4. Independent Hiring Manager review

Add a distinct Hiring Manager department and visible review state. It should receive the employer posting, source evidence, saved qualifications, and draft as reference data. Its separate skeptical instructions should seek reasons to reject the package, including missing requirements, weak or unsupported evidence, contradictions, confusing claims, keyword gaps, and incorrect or overconfident eligibility assumptions.

The reviewer may request revisions with specific findings tied to evidence. Resume/Application preparation revises, then the Hiring Manager reviews again. Permit at most three critique/revision cycles after the initial draft. A package that still fails is placed on quality hold with the unresolved findings; it has no approval/export action. Keep the reviewer as a separate department and queue stage, while sharing the selected local model to stay within the Mac's memory budget. The reviewer is a quality check, not a guarantee of hiring outcomes.

### 5. Human approval and package export

Only a package that passes all gates and the Hiring Manager review enters **Needs your review**. Present together:

- employer, role, location, verified application link, and posting evidence;
- why the role matched saved preferences and any eligibility details;
- tailored resume, cover letter, and answer drafts;
- evidence links for resume claims;
- the Hiring Manager's findings and how each was resolved;
- provider and review status.

The user can edit or reject the draft. Rejection may include a reason that returns the package to the relevant local queue stage. If the user adds a fact that is not in the saved evidence, they must confirm it as accurate (or add it to the profile) before it becomes supported material. Approval permits local export as a ZIP containing a simple, single-column ATS-friendly DOCX tailored resume and DOCX cover letter (standard text headings; no tables, columns, icons, or embedded graphics), editable application-answer notes, and job/source details. Approval never triggers an external request or submission. Keep the source resume unchanged.

## Components and data flow

Keep each stage behind a focused service boundary and communicate through the existing SQLite-backed queue:

1. **Source adapters** fetch public listings and normalize them into the existing job repository with source provenance.
2. **Verification and matching** recheck the employer page, apply deterministic role/location/eligibility gates, and persist gate results with reasons.
3. **Application preparation** takes an immutable snapshot of the accepted job and saved profile/resume, produces the tailored documents, and validates claim evidence.
4. **Hiring Manager review** reads that snapshot and draft, persists each critique cycle independently, and either returns actionable findings to preparation or releases the package to the review queue after all gates pass.
5. **Application approval/export** records the user's edit/decision and creates the local ZIP only after approval.
6. **Workspace API/UI** projects these persisted stages and results into the worker stations, item movement, activity, and Needs your review panel.

Persist source provenance, job verification time/result, gate outcomes, the fixed preparation snapshot, claim-to-evidence links, review cycles, user decision, and export location/status. Use migrations rather than rebuilding the existing SQLite database. Do not treat UI animation as task state; it must reflect these persisted transitions.

## Later phase: Project Engineering and QA

After the hiring workflow is complete, the Engineering department may find original portfolio-project opportunities by combining recurring skills from target job postings with free public sources such as the [GitHub REST API](https://docs.github.com/en/rest), the [Hacker News public API](https://github.com/HackerNews/API), and [arXiv's API](https://info.arxiv.org/help/api/index.html). Rank project ideas by relevance to actual target-role skills and show the source trail. Do not copy a source project; derive an original, appropriately scoped project.

X is not a default source. It can be considered only through an official, user-configured X API connection with access and potential cost shown before enabling it. CareerOS must not bypass X's published policy or access limits; see the [X developer policy](https://docs.x.com/developer-terms/policy) and [developer pricing](https://developer.x.com/).

Engineering works in an isolated staging workspace. A separate QA department runs reproducible checks and adversarial test cases, returns concrete failures to Engineering, and permits at most three repair cycles before holding the project. Run generated project code only in an isolated environment without CareerOS credentials and with external network access disabled by default. A project must be complete and QA-passed before CareerOS may offer it as resume evidence. Adding it to a portfolio or resume requires user approval. This phase is explicitly out of scope for the hiring release.

## UI and interaction

Retain the full-screen isometric neon pixel-art office and the integrated, slightly transparent side panels. The scene remains the primary view rather than a separate dashboard around the office. Show workers at their actual departments, with motion tied to queue activity; animate an item along connected belts only when work actually transitions between stations.

Hovering a worker shows its department, current role/task, status, time or latest update, and reason for waiting or holding. Keep **Needs your review** as the primary action. Its detail view contains all application evidence and controls without requiring the user to dispatch work. Settings and one-time setup remain compact. On narrow windows, preserve access through the current responsive drawer behavior.

## Runtime, provider, and privacy behavior

- One-time setup requires a resume, target role(s), and acceptable location(s). Eligibility facts are optional; when a posting depends on missing facts, hold it for review rather than guessing. The user does not supply per-task prompts or project ideas.
- Persist queue state, review cycles, gate outcomes, evidence references, and export history in SQLite. Use transactional/idempotent dispatch so restarts and repeated scans do not duplicate active or approved applications.
- Local Ollama is used for scheduled autonomous drafting and review. Limit concurrent inference to one task by default. Show when the model is missing or offline, and leave work queued/retryable without changing provider.
- For a user-selected OpenAI task, show the exact information snapshot that will leave the Mac and request per-task paid-use confirmation. Keep the API key outside SQLite and UI responses. Record provider, model, confirmation, and returned usage metadata when available. A cloud error ends that attempt; no silent fallback or automatic paid retry.
- CareerOS stores the profile, resume, jobs, reviews, and drafts locally. Bind to loopback by default. No data is sent to job sources other than the request needed to retrieve public listings; resume/profile information stays local unless the user confirms a particular cloud request.
- When the app closes or the Mac sleeps, processing stops; durable queued tasks continue after restart when the app and required local model are available. Do not imply 24/7 operation while the Mac is asleep or shut down.

## Failure handling

- If one source fails, record the source failure and continue using available sources and cached data. If every source fails, leave the scan failed/visible and preserve prior job records.
- On stale or ambiguous employer information, incomplete qualification details, unsupported resume evidence, or unresolved Hiring Manager findings, hold the role/package with a readable reason and no approval action.
- Persist task state transitions and safe retry metadata. Retry only transient fetch/worker failures with bounded backoff and idempotency. Do not automatically repeat an OpenAI request.
- Preserve the exact provider on each task. If Ollama is unavailable, wait or mark the local attempt failed for retry; do not switch to OpenAI.
- If a model produces malformed or unsupported output, reject it as a failed stage and retain enough diagnostics to retry or inspect without exposing secrets.
- Manual user edits must be revalidated before approval/export; a user edit must not bypass the verified-job requirement. Newly added facts require explicit user attestation before they count as evidence.

## Verification plan

Implement automated tests using temporary SQLite databases, fake planners, and mocked source responses. Do not call live job sites or real model APIs in the automated suite.

1. Parse SpeedyApply and existing feeds, handle malformed/stale entries, normalize employer links, and deduplicate repeat scans.
2. Verify role, location, employer-page, and eligibility gates; assert that uncertain jobs are held with a reason.
3. Verify tailored-resume claim traces, preservation of the base resume, and rejection of unsupported statements and conflicting answers.
4. Exercise Hiring Manager pass, critique/revision, three-cycle limit, held state, and the rule that held packages cannot be approved or exported.
5. Exercise persistent queue recovery, idempotent dispatch, bounded transient retries, source partial failure, and visible outage states.
6. Verify local-only unattended provider selection, explicit per-task cloud consent, data disclosure snapshot, no automatic cloud fallback/retry, and provider usage recording.
7. Run an end-to-end mocked workflow from scheduled discovery through verified role, tailored draft, critique/revision, user approval, and local package export. Assert that no external application-submission client or request is made.
8. Verify office worker states and hover details correspond to actual queue/review state and that approval remains accessible in the responsive side panel.

## Non-goals for the first release

- Automatically submitting applications, signing into applicant portals, sending LinkedIn messages, or bypassing site access controls.
- Engineering project generation or project QA implementation (specified above as a later phase).
- Guaranteed job eligibility, interview invitations, hiring outcomes, or fully accurate model judgments.
- Unattended use of a paid cloud model.
- A hosted multi-user service, cloud profile storage, or a dependency on paid job-search APIs.
