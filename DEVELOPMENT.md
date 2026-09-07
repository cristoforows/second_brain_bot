# Development Guide

## First-Time Setup

### 1. Clone and Install

```bash
git clone <repo-url>
cd second_brain_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # editable install + pytest/pytest-asyncio
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env   # fill in all required values — see README.md's Configuration table
```

Required at minimum: `TELEGRAM_BOT_TOKEN`, `GOOGLE_CLIENT_ID`,
`TOKEN_ENCRYPTION_KEY`, `OPENROUTER_API_KEY` — `Settings` construction raises
a clear error naming whichever is missing. Everything else has a sensible
default or is only needed for the mode you're running (webhook secrets for
`serve`, Drive/Telegram folder IDs for `summarize`).

Generate `TOKEN_ENCRYPTION_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Enable **Google Drive API** and **Google Calendar API** (Calendar is used
   by `/timebox`)
4. Create OAuth 2.0 credentials: APIs & Services → Credentials → Create
   Credentials → OAuth client ID
   - Application type: **Web application** (bot's per-user flow)
   - Add authorized redirect URI: `https://your-ngrok-url/oauth/callback`
5. Copy Client ID and Client Secret into `.env`

The bot requests `drive.file`, `drive.readonly`, and `calendar.events`.
Tokens minted before a scope was added lack it — re-run `/authenticate` to
upgrade.

The summarizer uses a *separate* OAuth token (`GOOGLE_SERVICE_REFRESH_TOKEN`,
default `./token.json`) with the `drive` scope, since it needs write access
across the whole knowledge base rather than just files it created. The first
run without a `token.json` present opens an interactive consent flow using
`client_secret.json` (a Desktop-app OAuth client) and saves the resulting
token.

### 4. Database Setup (Supabase or any Postgres)

```sql
CREATE TABLE user_tokens (
    user_id BIGINT PRIMARY KEY,
    encrypted_token TEXT NOT NULL,
    token_expires_at TIMESTAMP,
    last_accessed TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

Copy the connection details (host, port, database, user, password) to `.env`.

---

## Running Each Mode

```bash
.venv/bin/second-brain poll                                  # bot, local long-polling
.venv/bin/second-brain serve                                 # bot, webhook mode (needs a public URL)
.venv/bin/second-brain summarize --date yesterday --dry-run  # nightly pipeline, no writes/sends
.venv/bin/second-brain summarize --date 2026-06-01 -v        # a specific day, verbose
.venv/bin/second-brain index --changed path/to/File.md       # rebuild Directory.yaml along one path
.venv/bin/second-brain prompt "list all active projects"     # ad-hoc agent query
```

### Bot: polling vs. webhook

Both share the same handlers (`second_brain.bot.handlers.register_handlers`).

- **`poll`** — long-polls Telegram; no public URL needed. Best for iterating
  locally.
- **`serve`** — runs the Flask app under waitress; Telegram pushes updates
  via POST. Requires a public HTTPS URL (ngrok locally, or your deployed
  domain).

Telegram allows only **one** delivery method at a time — switching to local
polling implicitly stops webhook delivery until `serve` runs again (it
re-registers the webhook on start).

To test webhook mode locally:
```bash
ngrok http 8443
# WEBHOOK_URL=https://abc123.ngrok.io in .env, then:
.venv/bin/second-brain serve
```

### Summarizer: dry-run first

`--dry-run` skips every Drive write and Telegram send — the agent still
reads real Drive content and calls the real LLM (a few cents of usage), but
nothing is persisted or messaged. Always dry-run against a new
`VAULT_FOLDER_ID`/`INPUT_DRIVE_FOLDER_ID` pair before trusting it with writes.

On any failure (exception, `KeyboardInterrupt`, or a timeout from the LLM
call), `summarize` sends `❌ Summarizer failed for <date>: <error>` to
`SUMMARY_CHAT_ID` (skipped in dry-run), logs the traceback, and exits 1.

---

## Tests

```bash
.venv/bin/python -m pytest -q
```

Config comes from `[tool.pytest.ini_options]` in `pyproject.toml`
(`pythonpath = ["src"]`, `testpaths = ["tests"]`). `tests/conftest.py` sets
dummy values for the four required env vars via `os.environ.setdefault` —
never overriding a real `.env` — so the suite runs without any credentials.
Everything is offline: no Telegram, Drive, Postgres, or LLM calls (all
mocked).

```
tests/
  conftest.py       # env defaults + summarizer fixtures (sample_dump.md)
  bot/              # handlers, capture, google_auth, timebox_planner, calendar_handler, vault_agent, webhook
  summarizer/       # pipeline, agent, drive, drive_tools, telegram_tools, parser, timeutil, cli
```

---

## Project Layout

```
src/second_brain/
  cli.py                    # argparse: serve | poll | summarize | index | prompt
  core/
    config.py                # unified Settings (env + config.yaml) + module-level `config` singleton
    llm.py                   # the only place ChatOpenAI is constructed
    timeutil.py               # today/yesterday/capture_date (timezone-aware date math)
    logging.py                # structlog setup (JSON off a TTY, console on one) + bot's stdlib logging
    notify.py                 # send_telegram() — direct python-telegram-bot call, no HTTP hop
    models.py                 # Message, Category, RunResult
  bot/
    handlers.py               # command handlers + register_handlers (from bot.py)
    webhook.py                 # Flask app + serve() (from webhook_server.py)
    capture.py                 # Drive inbox file create/append/edit/delete (from drive_handler.py)
    google_auth.py             # OAuth flow, TokenStorage (Postgres), CSRF state
    search.py / vault_agent.py # /search command + the agentic vault walker
    timebox.py                  # /timebox conversation
    timebox_planner.py          # target-date + LLM schedule generation (from scheduler.py)
    calendar_handler.py         # Google Calendar writes for the schedule
  summarizer/
    pipeline.py                 # run_pipeline/run_prompt/run_index (from main.py, minus argparse)
    agent/                      # ReAct agent + PARA-filing system prompt
    tools/                      # drive_tools + telegram_tools (agent-facing @tool functions)
    drive.py                    # raw Drive API client (from services/drive.py)
    parser.py                   # dump file -> Message list
```

## Conventions

- **Timezone rule**: `APP_TIMEZONE` (default `Asia/Singapore`) is the single
  source of truth for any "what day is it" question — `/timebox`'s target
  day, `capture.py`'s `DAY_CUTOFF_HOUR` file naming, and the summarizer's
  "today"/"yesterday". Never use the container's local clock
  (`datetime.now()` without a timezone) for date-naming logic; always go
  through `core.timeutil`.
- **One LLM factory**: `core.llm.create_llm(api_key, model, *, timeout,
  max_tokens=None, temperature=None, provider=None)` is the only place
  `ChatOpenAI` is constructed. Callers pass their own timeout — 120s for
  `/timebox`/`/search`, 1800s for the summarizer's much longer agent runs.
- **Settings validation**: required fields raise a clear error naming the
  missing variable; `core.config.get_settings()` turns that into
  `sys.exit(1)` after logging it, matching the old bot's hard-exit behavior.
- Thin Telegram/CLI glue, judgment lives in the module it's named after
  (e.g. `timebox_planner` owns scheduling logic, `timebox.py` is just
  session state and keyboards) — keep new code following that split.

---

## Troubleshooting

**Webhook not receiving updates**
```bash
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
```
Verify ngrok is running and `WEBHOOK_URL` in `.env` matches it, then check
`second-brain serve`'s logs.

**Delete an existing webhook** (to switch to `poll` cleanly):
```bash
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/deleteWebhook
```

**OAuth callback fails after a bot restart** — the OAuth CSRF state cache is
in-memory. If the process restarts between `/authenticate` and completing
Google's consent screen, the callback fails with an invalid-state error.
Run `/authenticate` again.

**Summarizer can't find a dump file** — check `INPUT_DRIVE_FOLDER_ID` points
at the bot's *inbox* folder (`DRIVE_FOLDER_NAME`), not the knowledge base,
and that the date resolves the way you expect (`--date yesterday`/`today`
are timezone-aware via `APP_TIMEZONE`).
