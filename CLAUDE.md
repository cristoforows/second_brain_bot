# CLAUDE.md - AI Agent Context

## Mission

One package, one CLI (`second-brain`), two halves that share it:
- **The bot** captures Telegram messages into daily markdown files in Google
  Drive, in real time, plus `/timebox` (LLM scheduling) and `/search`
  (agentic vault search).
- **The summarizer** runs nightly, reads yesterday's dump, and files it into
  a PARA-hierarchy knowledge base on Drive via a LangGraph ReAct agent.

They used to be two repos talking over HTTP; now they're one process/image,
and the summarizer sends Telegram notifications directly with the bot's own
token (`core.notify`) instead of hopping through an HTTP endpoint.

## Layout

```
src/second_brain/
  cli.py                    # serve | poll | summarize | index | prompt
  core/
    config.py                 # unified Settings (env + config.yaml) + module-level `config`
    llm.py                    # the ONLY place ChatOpenAI is constructed
    timeutil.py               # today/yesterday/capture_date — timezone-aware date math
    logging.py                 # structlog (summarizer) + stdlib logging setup (bot)
    notify.py                  # send_telegram() via python-telegram-bot directly
    fly_machines.py             # minimal Fly Machines API client (list/create one-off machines)
    models.py                  # Message, Category, RunResult
  bot/
    handlers.py                # command handlers + register_handlers
    webhook.py                 # Flask app + serve(); registers jobs_api's blueprint
    jobs_api.py                 # POST /api/jobs/nightly-summary — starts the summarizer machine
    github_oidc.py               # verifies GitHub Actions OIDC bearer tokens for jobs_api
    capture.py                 # Drive inbox file create/append/edit/delete
    google_auth.py             # OAuth flow, TokenStorage (Postgres), CSRF state
    search.py / vault_agent.py  # /search command + agentic vault walker
    timebox.py / timebox_planner.py  # /timebox conversation + scheduling logic
    calendar_handler.py         # Google Calendar writes
  summarizer/
    pipeline.py                 # run_pipeline / run_prompt / run_index
    agent/                      # ReAct agent + PARA-filing system prompt
    tools/                      # drive_tools + telegram_tools (@tool functions)
    drive.py                    # raw Drive API client
    parser.py                   # dump file -> Message list
tests/{bot,summarizer}/       # offline test suites, no real network calls
```

## Key Modules (one line each)

- `cli.py` — argparse dispatch; owns the bot polling entrypoint and the
  summarizer's failure-notification wrapping.
- `core/config.py` — one pydantic-settings `Settings`; required fields
  (`TELEGRAM_BOT_TOKEN`, `GOOGLE_CLIENT_ID`, `TOKEN_ENCRYPTION_KEY`,
  `OPENROUTER_API_KEY`) raise a clear error, not a silent default.
- `core/llm.py` — `create_llm(api_key, model, *, timeout, max_tokens=None,
  temperature=None, provider=None)`; callers own their own timeout.
- `bot/handlers.py` — auth gate, then dispatch to `capture`/`timebox`/`search`.
- `bot/capture.py` — per-day markdown file, honoring `DAY_CUTOFF_HOUR` in
  `APP_TIMEZONE` (via `core.timeutil.capture_date`), never the container clock.
- `bot/webhook.py` — binds the port before importing the heavy bot stack
  (cold-start latency), gates routes on `_bot_ready()`.
- `summarizer/pipeline.py` — finds the dump, parses it, runs the agent, sends
  notifications; falls back to to-do maintenance when there's nothing to file.
- `summarizer/agent/prompts.py` — the PARA-filing system prompt; tune here.
- `bot/jobs_api.py` — `POST /api/jobs/nightly-summary`: OIDC-verified,
  independent of `_bot_ready()`, starts the summarizer via `core.fly_machines`.
- `bot/github_oidc.py` — verifies a GitHub Actions OIDC token's signature
  (GitHub's JWKS) and claims (repo/ref/workflow/event) against an allowlist;
  raises `OidcRejected`(401) / `PolicyRejected`(403) / `OidcUnavailable`(503).

## Run / Test

```bash
pip install -e ".[dev]"
.venv/bin/second-brain poll                                   # bot, local
.venv/bin/second-brain summarize --date yesterday --dry-run   # summarizer, no writes
.venv/bin/python -m pytest -q                                  # full suite, offline
```

## Conventions

- **Timezone rule**: `APP_TIMEZONE` (default `Asia/Singapore`) is the single
  source of truth for "what day is it" — `/timebox` target-day math,
  `capture.py`'s day-cutoff file naming, and the summarizer's
  today/yesterday. Never call `datetime.now()` without a timezone for
  date-naming logic; go through `core.timeutil`. `TIMEBOX_TIMEZONE` is a
  deprecated env alias, still honored with a warning.
- **One LLM factory**: never construct `ChatOpenAI` directly — go through
  `core.llm.create_llm`.
- Thin glue, judgment lives in the module named for it (`timebox_planner`
  owns scheduling; `timebox.py` is session state and keyboards only).
- Settings validation failures should name the missing/invalid variable, not
  fail silently or generically.
- `--dry-run` on the summarizer must skip both Drive writes and Telegram
  sends — check both when adding a new write/notify path.
- `summarize` installs handlers for SIGTERM (the job machine's external
  `timeout` wrapper) and SIGALRM (`SUMMARIZER_MAX_SECONDS`) so a hang or
  external kill still produces a Telegram failure notice instead of the
  process just vanishing — see `cli.JobTerminated`/`cli.JobTimedOut`.
- `config.yaml` is found via `SECOND_BRAIN_CONFIG` env var, then
  `./config.yaml`, then the repo root — never assume an editable install;
  the repo-root fallback only works for one.

## Token Storage

Bot: PostgreSQL (`DATABASE_*`), one row per user, encrypted via Fernet
(`TOKEN_ENCRYPTION_KEY`). Summarizer: a separate OAuth token file
(`GOOGLE_SERVICE_REFRESH_TOKEN`, or `GOOGLE_TOKEN_JSON` content in CI/Fly)
with the broader `drive` scope, since it writes across the whole vault
rather than just files it created.

## See Also

- [CONTEXT.md](CONTEXT.md) — canonical domain terms (Timebox Session, Target
  Date, Schedule, Target Calendar)
- `docs/adr/` — architecture decision records
- [README.md](README.md) — user-facing overview and configuration reference
- [DEVELOPMENT.md](DEVELOPMENT.md) / [DEPLOY.md](DEPLOY.md) — setup and Fly
  deployment
