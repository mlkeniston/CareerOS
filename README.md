# CareerOS

CareerOS is a local-first workspace for finding technology internships and jobs, preparing application and LinkedIn outreach drafts, and making progress on portfolio projects. The app stores its database, resumes, and portfolio files on your Mac. It does not submit applications, send messages, publish code, or execute generated files.

## What works in this MVP

- Search cached job listings, refresh public job feeds, and scan the public SpeedyApply college jobs list without requiring a search prompt.
- Save a career profile and plain-text resume versions locally.
- Ask a planner to prepare a cover letter, resume-alignment notes, answers, and next steps. Edit and approve the draft before exporting Markdown.
- Automatically prepare LinkedIn connection notes and follow-up drafts for matching roles when a profile and resume are saved. Edit and approve them before copying.
- Let Engineering collect public project ideas from GitHub, Hacker News, and arXiv, then build a local proposal when job listings reveal recurring skills. An independent Project QA worker runs isolated checks, critiques the result, and sends concrete defects back for up to three repair rounds. You review the QA report before approving project files.
- Keep a persistent SQLite task queue and recover local work after restart.
- Navigate every department from a persistent indie pixel-art side panel, with a dedicated male QA worker at the Project QA bench. Project handoffs animate as workers meet and exchange an item. On smaller screens, panels open as drawers. Drag the office or use the arrow keys to orbit; press Home or RESET to return to the starting view. Hover over a worker for its task, status, timing, and task ID; click for more detail.
- Start unattended local job discovery automatically and repeat every six hours while CareerOS is running.

## Requirements

- macOS on Apple silicon or another machine running Python 3.11 or newer.
- Ollama for local planning. The default model is `qwen2.5:1.5b`, a small model selected to fit an 8 GB Mac more comfortably than larger models. Local speed and writing quality depend on the machine and model build.
- Docker Desktop is required for active Project QA. Generated project files are never run directly on macOS.
- OpenAI API access is optional. The cloud planner uses the verified API model ID `gpt-6-luna`. OpenAI's published standard rates checked on 2026-10-09 are $0.10 per million input tokens and $0.50 per million output tokens. API usage is billed separately from ChatGPT plans, and the API free tier is not supported. See the [official model page](https://developers.openai.com/api/docs/models/gpt-6-luna) for current access and pricing.

## Run locally

1. Install Python 3.11+ and [Ollama](https://ollama.com/download). Open the Ollama Mac app so its local service is running.
2. Open Terminal in this folder and create an environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   pip install -e '.[dev]'
   ```

3. Download the local models while Ollama is running:

   ```bash
   ollama pull qwen2.5:1.5b
   ollama pull qwen3.5:2b-q4_K_M
   ```

   If you use Ollama without its Mac app, run `ollama serve` in a separate Terminal window and leave it open while CareerOS is running.

   LinkedIn Outreach uses its own Ollama model so its worker can be configured independently. The default `qwen3.5:2b-q4_K_M` tag is about 1.9 GB; install it once with the command above. If the model is missing, the office shows the exact install command and pauses outreach drafts until it is ready. Resume content stays on this Mac.

4. Prepare the isolated Project QA image (Docker Desktop must be running):

   ```bash
   careeros sandbox prepare
   careeros sandbox check
   ```

5. Start CareerOS in another Terminal window:

   ```bash
   careeros
   ```

   Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). The default bind address is loopback, so other devices cannot reach the app.

The first start creates `data/careeros.sqlite3`. Back up the `data/` folder to preserve your local profile, resumes, saved jobs, outreach drafts, task history, QA reports, and portfolio workspace.

## Office autopilot

When CareerOS starts, the office worker queues a public listing scan automatically. It repeats every six hours while the app is open. Discovery reads the configured public job feeds and stores results in the local database; it does not need your profile, resume, API key, or search terms. The default Arbeitnow feed is included. Optional Greenhouse and Lever boards can be added below.

The office shows each worker's actual queue state. Drag the scene left or right, or focus the canvas and use the arrow keys, to orbit around the isometric map; **Home** or **RESET** restores the original view. Hover over a worker for its current task and status, or select a worker or room for more detail. Use **AUTO ON** to pause future scans; work already queued is allowed to finish. Closing CareerOS stops the worker; the next scan runs after you reopen it if six hours have elapsed. The saved schedule prevents duplicate scans when the app restarts. The office shows queued local work only while CareerOS and your Mac are awake. Queued items remain in the local database across app or Mac restarts, and local Ollama tasks interrupted while running are recovered for another attempt when CareerOS starts. Transient local failures can be retried within a bounded attempt limit; cloud requests are never retried automatically. Visual movement follows stored workflow transitions, so the office reflects recorded handoffs and task state.

Job discovery works without Ollama. To let CareerOS prepare a matching application draft automatically, save target roles and at least one resume version in Resume Team, then keep the configured local Ollama model available. A prepared application stays in Draft review until you inspect and approve it. CareerOS never submits an application. If Ollama is unavailable, discovery continues and the office shows the affected task state.

LinkedIn Outreach uses the same saved target roles, preferred locations, and resume. Preferred locations guide automatic application and outreach draft selection; an empty location list leaves role matching unrestricted. Listings outside those preferences stay in the searchable job cache. For the best drafts, add a short profile summary and skills in Resume Team. CareerOS prepares one local draft for a suitable role and shows the connection note, follow-up, and resume evidence in the Outreach station. Connection notes are capped at 200 characters to fit LinkedIn's current Basic invitation limit. Review and approve the wording, then choose a person and send it yourself from LinkedIn. For privacy, the worker waits without queuing drafts if `OLLAMA_BASE_URL` points anywhere except this Mac. CareerOS does not sign into LinkedIn, find contacts, or send messages.

The Engineering team selects sourced ideas based on skills that recur in discovered listings, then generates a proposal and test manifest locally. Project QA runs the manifest in a Docker container with networking disabled, a read-only project mount, resource limits, and a non-root user. If the sandbox is unavailable or a check fails, CareerOS holds or revises the project; it never runs generated code directly on your Mac. The QA model reviews only after deterministic checks pass. Concrete findings go back to Engineering for up to three cycles. Unresolved findings, malformed QA output, or an unavailable sandbox leave the project on quality hold. Open the Portfolio Workshop to read citations, QA findings, and staged files. Approval is still yours, and approved files are only copied into the managed portfolio folder when you explicitly apply them.

## Project QA sandbox

Project checks run only inside a local Docker container with networking disabled, a read-only project mount, resource limits, and a non-root user. Install Docker Desktop, then prepare and check the image:

```bash
careeros sandbox prepare
careeros sandbox check
```

If Docker or the sandbox image is unavailable, project QA stays held. Install Docker Desktop, start it, and run `careeros sandbox prepare` followed by `careeros sandbox check`. CareerOS never falls back to running generated project code on macOS.

## Optional OpenAI planner

1. Copy `.env.example` to `.env`.
2. Add an OpenAI API key to `.env` as `OPENAI_API_KEY=...`.
3. Restart CareerOS and choose OpenAI in Planner Corner or for an individual task.

Choosing OpenAI as the default does not make an API request. Before every OpenAI task, CareerOS shows what information that task will send and asks you to confirm paid use. A failed or interrupted cloud task is never retried automatically; start a new task and confirm again if you want another request. API keys are read from `.env` or the process environment and are never stored in SQLite or returned by the settings API. Do not commit `.env`.

## Job board configuration

The app scans its configured public job-board feeds during automatic discovery and manual refresh. You can also configure public employer boards by comma-separated board IDs:

```dotenv
CAREEROS_GREENHOUSE_BOARDS=acme,example-company
CAREEROS_LEVER_SITES=another-company
```

The connectors fetch public board listings without credentials. Feed refresh sends only your search filters; it never sends your profile or resume. If a feed is unavailable, cached listings remain searchable.

### Employer checks and retries

CareerOS keeps source, employer, and application links separate so you can see where each listing came from. Before an automatic application package is prepared, CareerOS checks the public employer posting and requires the employer, role, U.S. location, posting detail, and saved eligibility facts to pass. Every result remains visible on the Job Board:

- **Employer verified** means the public primary posting matched the expected company and role and contained enough current detail.
- **Access restricted** means the public page returned HTTP 403 or otherwise required access CareerOS does not have. It does not mean the job is fake or closed. CareerOS does not bypass sign-in pages, CAPTCHAs, or access controls.
- **Posting closed** covers an explicit closure notice or a stale HTTP 404/410 page.
- **Employer or role mismatch** means the primary posting did not match the listing identity.
- **Posting needs more detail** means the public page did not provide enough evidence for the hard gate.
- **Temporary check problem** covers timeouts, HTTP 429, and temporary server errors. CareerOS retries only this class, at most three automatic attempts with a delay between attempts.
- **Unsafe destination blocked** means a URL, redirect, or DNS result pointed somewhere CareerOS will not contact, such as a private network address or an HTTPS downgrade.

Use **Check employer posting** on a confirmed U.S. role for a manual recheck. A temporary outcome uses the clearer **Retry employer check** label. Manual checks use the same safety rules and do not create an application, call a planner, submit anything, or reset an exhausted automatic retry budget. Permanent and unsafe outcomes remain held until a later manual check produces verified evidence.

Hover over the Job Hunter worker or click it to see the latest scan totals: roles found, verified postings, held outcomes by class, scheduled transient retries, and source failures. One failed source or listing does not stop unrelated listings, and cached jobs remain available when a source is temporarily unavailable.

## Data and safety

- Profiles, resume text, saved listings, and task records live in the local SQLite database.
- Portfolio proposals are staged under `data/portfolio/.staging/`; approved files can only be applied below `data/portfolio/<project-id>/`.
- The portfolio worker stores proposed programs as text and does not run them or invoke a shell.
- Application approval only permits a local Markdown export; it does not submit or send anything.
- LinkedIn outreach drafts and approvals stay in the local database. Approval only allows copying the message; it does not select a contact or send anything.
- CareerOS has no account, cloud sync, or paid job-board service.

## Tests

Run the Python suite and the office renderer tests with:

```bash
pytest -q
node --test tests/*.test.mjs
```

Tests use a temporary SQLite database, a fake planner, and mocked job feeds. They do not call Ollama, OpenAI, or live job sites.

## Configuration

Copy `.env.example` to `.env` to customize settings. The supported variables are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAREEROS_DATA_DIR` | `data` | Local database and portfolio folder |
| `CAREEROS_HOST` | `127.0.0.1` | Loopback bind address |
| `CAREEROS_PORT` | `8000` | Local web port |
| `CAREEROS_WORKER_ENABLED` | `true` | Start the task worker with the app |
| `CAREEROS_PLANNER_PROVIDER` | `ollama` | Initial planner selection |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama address |
| `OLLAMA_MODEL` | `qwen2.5:1.5b` | Local model tag |
| `CAREEROS_OUTREACH_MODEL` | `qwen3.5:2b-q4_K_M` | Dedicated local model for LinkedIn outreach drafts |
| `OPENAI_API_KEY` | unset | Optional API credential for GPT-6 Luna |
| `CAREEROS_GREENHOUSE_BOARDS` | empty | Optional public Greenhouse board IDs |
| `CAREEROS_LEVER_SITES` | empty | Optional public Lever site IDs |

CareerOS rejects non-loopback bind addresses to keep the single-user MVP local.

## License

MIT. See [LICENSE](LICENSE).
