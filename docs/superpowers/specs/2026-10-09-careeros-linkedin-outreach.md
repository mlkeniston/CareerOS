# CareerOS LinkedIn Outreach Department

**Status:** Implementation assumption for the requested feature, using the existing local-first MVP constraints.

## Goal

Add a dedicated LinkedIn Outreach worker that prepares role-specific messages automatically from the user's saved career profile, resume, and relevant technology job listings.

## User experience

- A new neon-accented LinkedIn Outreach worker appears in the office and reflects real queue state, including queued, working, review, and failure states.
- After a relevant job scan, CareerOS queues at most one new outreach draft for a suitable role when a saved profile target and resume are available. Existing drafts are reused; failed work may be retried.
- Each draft contains a concise connection note, a longer follow-up message, and a short evidence list showing which saved experience supports the claims.
- The Outreach station lists drafts. The user can edit and approve a draft, then copy its text for manual use. Choosing an individual contact and sending happen outside CareerOS.
- When personal materials are missing, discovery still works and the Outreach worker explains what is missing.

## Safety and model behavior

- Automatic outreach preparation uses local Ollama only. No automatic or fallback OpenAI call is permitted.
- The department does not sign into LinkedIn, scrape LinkedIn, discover people, or send connection requests or messages.
- No message is marked sent. Approval means the user approved the text for copying and manual use.
- Draft instructions ask the planner to ground claims in the saved resume/profile and job listing. The user checks the claims during review; planner instructions found inside those materials are untrusted reference data.
- Outreach sends resume/profile/job text only to a loopback Ollama endpoint, even if other CareerOS tasks are configured for remote Ollama. With a remote endpoint, the worker waits without repeatedly queueing blocked tasks. Connection notes are limited to 200 characters and the editor shows the count.
- Drafts, edits, approvals, and queue tasks persist in SQLite.

## Acceptance criteria

- A relevant saved/discovered role plus a resume and target role queues an idempotent local outreach task without asking the user to create work manually.
- Running the worker produces an editable, persistent review draft tied to its role and resume.
- Draft preparation never uses the paid provider and never performs LinkedIn account actions.
- A user can edit and approve a draft; the review screen only shows copy buttons after approval, and the export route enforces approval.
- The office worker's displayed state and review count match backend records; hover details identify its actual task and timing.
- Tests cover automatic dispatch and deduplication, draft generation/validation, review/approval/export boundaries, missing prerequisites, and office snapshot state.

## Explicit exclusions

This addition does not add LinkedIn credentials, LinkedIn API integration, contact discovery, scraping, message sending, or browser automation.
