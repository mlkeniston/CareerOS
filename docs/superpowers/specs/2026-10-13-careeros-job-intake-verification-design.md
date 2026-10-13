# CareerOS Job Intake and Verification Redesign

**Status:** Proposed for review  
**Date:** 2026-10-13

## Goal

Make CareerOS's automatic U.S. job discovery and application preparation reliable across supported job sources, while keeping employer evidence checks, local-first processing, and the user's approval before any application package is exported.

## Current failure

CareerOS imports listings from public feeds and the SpeedyApply index, then uses one generic HTTP verifier for every employer page. That verifier refuses all redirects, expects the primary page's visible title and company text to match strictly, and reports non-200 responses as holds. Discovery records a held reason but does not queue resume preparation when any required gate fails. The result is safe but brittle: ordinary ATS redirects, bot-blocked pages, stale links, and page-layout differences can all stop an otherwise useful listing before a model or reviewer is involved.

The reference `ai-job-search` project uses portal-specific search tools, lets the user select a listing, and permits a job description to be pasted when a page cannot be fetched. CareerOS must retain its approved autonomous discovery and preparation model; it should improve source handling rather than require the user to dispatch each job manually.

## Design

### 1. Source-specific listing records

Keep each source behind an adapter. Adapters normalize a listing while preserving:

- source name and source listing URL;
- canonical employer or ATS posting URL and application URL as separate fields;
- employer name, job title, location, and source requisition ID when available;
- source publication/update date and CareerOS fetch time.

Use official public feeds, public repository data, or documented public ATS endpoints where available. Do not treat an aggregator or index page as the employer posting. Do not infer that a listing is still open from its title or cached description.

### 2. Safe, bounded page resolution

Resolve ordinary employer redirects manually rather than enabling automatic HTTP redirect following. For every hop:

1. Resolve relative `Location` values against the current URL.
2. Accept only HTTP or HTTPS URLs without credentials; reject HTTPS-to-HTTP downgrade.
3. Resolve the destination host, require every returned address to be public, and pin the request to a validated address while preserving host and TLS SNI.
4. Stop on a loop, unsafe address, invalid URL, or more than five redirects.

Fetch only the final safe public destination. Preserve the original source URL and store the final resolved employer URL separately. Do not spoof browser identities, bypass access controls, or attempt authenticated access.

### 3. Structured identity and detail evidence

Prefer source-provided requisition IDs and structured posting fields, including `JobPosting` metadata and supported ATS detail responses. Use visible page text as a fallback. Normalize common title/company variants and punctuation, but require positive evidence that the primary posting is the same role; text from related-job lists, navigation, or other roles does not qualify.

The verifier returns a typed outcome and evidence summary, not just a Boolean:

- `verified`: identity and minimum detail evidence passed;
- `closed`: the employer page identifies the posting as closed or expired;
- `identity_mismatch`: the primary posting conflicts with the listed company or role;
- `insufficient_detail`: the page loaded but did not provide enough readable job evidence;
- `access_restricted`: the source refused automated access, such as HTTP 403;
- `not_found`: the employer page returned 404 or 410;
- `transient_error`: throttling, server error, timeout, or temporary network failure;
- `unsafe_destination`: URL, redirect, DNS, or address failed a safety check.

Persist the human-readable reason, checked URL, final URL when safe, timestamp, and evidence fingerprint. Keep the existing compatibility status (`verified` or `held`) for application gates while adding a machine-readable outcome code through a forward SQLite migration.

### 4. Independent, recoverable job processing

One bad listing or source must never stop other listings. Each discovered role progresses independently through source enrichment, verification, matching, drafting, and review. Retry only transient failures with bounded backoff and idempotency; do not repeatedly retry permanent or unsafe outcomes. Manual **Check employer posting** remains available for a confirmed U.S. listing.

All required gates remain hard gates: confirmed U.S. location, target-role and preferred-location match, sufficient posting details, material eligibility, evidence-grounded resume claims, and Hiring Manager clearance. Only fully cleared packages reach human review. No verification outcome enables automatic submission or sends a resume to the employer.

### 5. Status visibility

Job cards show the verifier outcome, plain-language reason, and last checked time. They show a recheck action for U.S. listings where a recheck is safe. The Job Hunter worker summary reports per-scan counts for verified, held by reason, and transient failures, plus source failures. The UI distinguishes inaccessible listings from jobs verified as closed or mismatched.

If an employer site does not expose enough information through an allowed public interface, hold that listing with a clear reason and continue processing other jobs. CareerOS cannot guarantee access to every external site; it must make those failures understandable and recoverable instead of presenting them as unexplained application errors.

## User-visible workflow

1. Job Discovery refreshes configured sources on its existing schedule and stores every valid listing with provenance.
2. Each U.S. listing is enriched from its source adapter and safely resolved to its employer posting.
3. Verified, sufficiently detailed, role-matched listings continue through resume preparation and independent Hiring Manager review.
4. A held listing displays a specific reason and, for transient or re-checkable cases, a retry control. Other jobs continue without waiting for it.
5. The user approves each cleared application package; CareerOS prepares files for the user to submit.

The default planner remains local Ollama. OpenAI remains an explicit, per-task option with existing paid-use confirmation. Discovery and verification never invoke an LLM to invent posting facts.

## Failure and safety policy

- Hold an uncertain identity, unsafe URL, unresolved eligibility condition, or insufficient employer evidence.
- Retry only transient network, throttling, and server failures with a small bounded attempt count and backoff.
- Treat 403 as access restricted, not proof that a job is fake or expired; do not bypass access restrictions.
- Treat 404/410 as not found and retain the listing for visibility; identify explicit closed/expired notices separately; do not draft from cached or third-party text alone.
- Keep private/reserved DNS rejection, per-hop validation, body-size and timeout limits, and no credential forwarding.
- Preserve cached listings and their provenance when one source is unavailable.
- Keep all user profile and resume data local unless the user explicitly confirms a particular OpenAI task.
- Never submit applications, log into employer portals, or silently change providers.

## Acceptance criteria

1. Relative and absolute public redirects resolve through at most five individually validated hops; loops, downgrade, private/reserved DNS, and unsafe schemes remain held.
2. Supported sources retain distinct source, employer, and application URLs, along with requisition IDs and timestamps when provided.
3. Common title and company formatting variants pass only when the same primary posting is supported by structured or visible evidence; a genuinely different role remains held.
4. Each failure class is persisted and visible on its job card; a retryable failure can be rechecked without duplicating applications.
5. Transient retries are bounded and do not repeat a finished LLM task or use a paid provider.
6. A failure on one listing or source does not block other verified jobs or erase cached results.
7. The application pipeline still requires every deterministic gate and Hiring Manager clearance, and still stops before external submission.
8. Automated tests use mocked HTTP, DNS, sources, and planners only; they cover redirect safety, identity matching, response classification, retry idempotency, and a complete mocked discovery-to-review flow.

## Out of scope

- Rebuilding the office interface, resume editor, project engineering, or Project QA departments.
- Requiring the user to pick and dispatch each listing individually.
- Browser automation, logins, CAPTCHA solving, identity spoofing, or bypassing site access controls.
- Guaranteeing that every public job board or employer page remains reachable or that every listing is current.
- Automatic application submission or unattended paid-model fallback.
