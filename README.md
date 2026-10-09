# CareerOS

CareerOS is a local-first workspace for finding technology internships and jobs, preparing application and LinkedIn outreach drafts, and making progress on portfolio projects. The app stores its database, resumes, and portfolio files on your Mac. It does not submit applications, send messages, publish code, or execute generated files.

## What works in this MVP

- Search cached job listings, refresh the public Arbeitnow feed, optionally add public Greenhouse and Lever boards, or add a listing by hand.
- Save a career profile and plain-text resume versions locally.
- Ask a planner to prepare a cover letter, resume-alignment notes, answers, and next steps. Edit and approve the draft before exporting Markdown.
- Automatically prepare LinkedIn connection notes and follow-up drafts for matching roles when a profile and resume are saved. Edit and approve them before copying.
- Give the portfolio worker a project brief, inspect its proposed files and diffs, approve them, then apply them inside the managed portfolio folder.
- Keep a persistent SQLite task queue and recover local work after restart.
- See queue-backed workers moving through a full-screen, isometric pixel-art office. Drag the scene or use the arrow keys to orbit; press Home or RESET to return to the starting view. Hover over a worker for its task, status, timing, and task ID; click for more detail.
- Start unattended local job discovery automatically and repeat every six hours while CareerOS is running.

## Requirements

- macOS on Apple silicon or another machine running Python 3.11 or newer.
- Ollama for local planning. The default model is `qwen2.5:1.5b`, a small model selected to fit an 8 GB Mac more comfortably than larger models. Local speed and writing quality depend on the machine and model build.
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

3. Download both local models while Ollama is running:

   ```bash
   ollama pull qwen2.5:1.5b
   ollama pull qwen3.5:2b-q4_K_M
   ```

   If you use Ollama without its Mac app, run `ollama serve` in a separate Terminal window and leave it open while CareerOS is running.

   LinkedIn Outreach uses its own Ollama model so its worker can be configured independently. The default `qwen3.5:2b-q4_K_M` tag is about 1.9 GB; install it once with the command above. If the model is missing, the office shows the exact install command and pauses outreach drafts until it is ready. Resume content stays on this Mac.

4. Start CareerOS in another Terminal window:

   ```bash
   careeros
   ```

   Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). The default bind address is loopback, so other devices cannot reach the app.

The first start creates `data/careeros.sqlite3`. Back up the `data/` folder to preserve your local profile, resumes, saved jobs, outreach drafts, task history, and portfolio workspace.

## Office autopilot

When CareerOS starts, the office worker queues a public listing scan automatically. It repeats every six hours while the app is open. Discovery reads the configured public job feeds and stores results in the local database; it does not need your profile, resume, API key, or search terms. The default Arbeitnow feed is included. Optional Greenhouse and Lever boards can be added below.

The office shows each worker's actual queue state. Drag the scene left or right, or focus the canvas and use the arrow keys, to orbit around the isometric map; **Home** or **RESET** restores the original view. Hover over a worker for its current task and status, or select a worker or room for more detail. Use **AUTO ON** to pause future scans; work already queued is allowed to finish. Closing CareerOS stops the worker; the next scan runs after you reopen it if six hours have elapsed. The saved schedule prevents duplicate scans when the app restarts.

Job discovery works without Ollama. To let CareerOS prepare a matching application draft automatically, save target roles and at least one resume version in Resume Team, then keep the configured local Ollama model available. A prepared application stays in Draft review until you inspect and approve it. CareerOS never submits an application. If Ollama is unavailable, discovery continues and the office shows the affected task state.

LinkedIn Outreach uses the same saved target roles and resume. For the best drafts, add a short profile summary and skills in Resume Team. CareerOS prepares one local draft for a suitable role and shows the connection note, follow-up, and resume evidence in the Outreach station. Connection notes are capped at 200 characters to fit LinkedIn's current Basic invitation limit. Review and approve the wording, then choose a person and send it yourself from LinkedIn. For privacy, the worker waits without queuing drafts if `OLLAMA_BASE_URL` points anywhere except this Mac. CareerOS does not sign into LinkedIn, find contacts, or send messages.

The portfolio worker can stage a project proposal after the job feed contains recurring technology skill evidence. It uses the local planner, and its files remain staged for your review. CareerOS does not run generated code or apply proposal files without your approval.

## Optional OpenAI planner

1. Copy `.env.example` to `.env`.
2. Add an OpenAI API key to `.env` as `OPENAI_API_KEY=...`.
3. Restart CareerOS and choose OpenAI in Planner Corner or for an individual task.

Choosing OpenAI as the default does not make an API request. Before every OpenAI task, CareerOS shows what information that task will send and asks you to confirm paid use. A failed or interrupted cloud task is never retried automatically; start a new task and confirm again if you want another request. API keys are read from `.env` or the process environment and are never stored in SQLite or returned by the settings API. Do not commit `.env`.

## Job board configuration

The app uses the public Arbeitnow job-board feed on a manual refresh. You can also configure public employer boards by comma-separated board IDs:

```dotenv
CAREEROS_GREENHOUSE_BOARDS=acme,example-company
CAREEROS_LEVER_SITES=another-company
```

The connectors fetch public board listings without credentials. Feed refresh sends only your search filters; it never sends your profile or resume. If a feed is unavailable, cached listings remain searchable.

## Data and safety

- Profiles, resume text, saved listings, and task records live in the local SQLite database.
- Portfolio proposals are staged under `data/portfolio/.staging/`; approved files can only be applied below `data/portfolio/<project-id>/`.
- The portfolio worker stores proposed programs as text and does not run them or invoke a shell.
- Application approval only permits a local Markdown export; it does not submit or send anything.
- LinkedIn outreach drafts and approvals stay in the local database. Approval only allows copying the message; it does not select a contact or send anything.
- CareerOS has no account, cloud sync, or paid job-board service.

## Tests

Run the suite with:

```bash
pytest -q
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
