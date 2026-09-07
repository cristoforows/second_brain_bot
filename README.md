# Second Brain

A Telegram bot that captures your messages into Google Drive, plus a nightly
AI agent that organizes those captures into a living PARA-method knowledge
base. One installable Python package (`second-brain`), one CLI, one Docker
image, one test suite.

## What It Does

**The bot** (`second-brain serve` / `second-brain poll`):
- Listens to messages you send in Telegram
- Authenticates you via Google OAuth 2.0 (`/authenticate`)
- Appends each message to a daily markdown file (`YYYY-MM-DD.md`) in your
  Google Drive inbox folder — editing a Telegram message updates the same
  entry in Drive; deleting one removes it
- `/timebox` — an LLM (OpenRouter via LangChain) turns next-day tasks into a
  timeboxed schedule, optionally published to a dedicated Google Calendar
- `/search` — an LLM-driven agent walks your Drive knowledge base (written by
  the summarizer, below) to answer questions over your notes
- Exposes `POST /api/send-message`, a shared-secret-gated endpoint any
  trusted caller can use to make the bot send a Telegram message

**The summarizer** (`second-brain summarize`), run nightly as a one-off job:
- Reads yesterday's dump file (`YYYY-MM-DD.md`) from the bot's inbox folder
- Parses individual messages (delimited by `<!-- msg_id: {id} -->` comments)
- An AI agent (LangGraph ReAct loop) classifies each message into a PARA
  section (to-do, projects, areas, resources, archives), files it into the
  right topic folder, merges it with existing notes, and keeps each folder's
  `Directory.yaml` index up to date
- Sends a run summary and an active to-do digest to your Telegram, straight
  from the bot's own token (no HTTP hop between the two halves anymore — they
  share one process/image)
- `second-brain index` rebuilds `Directory.yaml` files across the knowledge
  base; `second-brain prompt "..."` runs the agent with an ad-hoc query

Think of the bot as the capture layer and the summarizer as the filing
clerk: everything you send in Telegram lands in Drive immediately, and once
a day it gets organized into a searchable knowledge base you can `/search`
from the same bot.

```
Telegram ──(bot, real-time)──▶ inbox/YYYY-MM-DD.md (Google Drive)
                                        │
                          (summarizer, nightly, reads yesterday's file)
                                        ▼
                          knowledge base (Drive, PARA hierarchy)
                                        │
                          (bot, on demand)
                                        ▼
                                    /search
```

## Requirements

- Python 3.11+ (the Docker image is built on 3.12)
- A Telegram account and a bot token from [@BotFather](https://t.me/BotFather)
- A Google account with the Drive API (and Calendar API, for `/timebox`)
  enabled
- An [OpenRouter](https://openrouter.ai/keys) API key — required by
  `/timebox`, `/search`, and the summarizer
- A PostgreSQL database (e.g. [Supabase](https://supabase.com)) for the
  bot's per-user token storage

## Quick Start

```bash
git clone <repo-url>
cd second_brain_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env with your credentials — see Configuration below

.venv/bin/second-brain poll                        # local bot, long-polling
.venv/bin/second-brain summarize --date yesterday --dry-run   # summarizer, no writes
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full local setup (Google Cloud
project, Postgres schema, ngrok for webhook testing) and
[DEPLOY.md](DEPLOY.md) for the Fly.io production deployment.

## CLI

```
second-brain serve                              # production webhook server (Flask/waitress)
second-brain poll                               # local long-polling bot (no public URL needed)
second-brain summarize [--date D] [--dry-run] [--verbose]
                                                 # run the nightly pipeline once (D: YYYY-MM-DD, "yesterday", or "today"; default yesterday)
second-brain index [--changed PATH ...] [--dry-run]
                                                 # rebuild Directory.yaml files
second-brain prompt "TEXT" [--dry-run]          # run the summarizer agent with an ad-hoc prompt
```

## Bot Commands (Telegram)

- `/start`, `/help` — introduction and command list
- `/authenticate` — connect your Google Drive via OAuth 2.0
- `/search <query>` — ask a question over your organized knowledge base
- `/timebox` — turn next-day tasks into a timeboxed schedule (optionally
  written to Google Calendar)
- `/status` — check authentication and Drive connection status
- `/logout` — disconnect Google Drive and remove stored tokens

Once authenticated, any plain-text message is saved to today's markdown file
in your Drive inbox folder.

### Outbound Send-Message API

`POST /api/send-message` lets a trusted caller make the bot send a Telegram
message. Disabled unless `OUTBOUND_API_SECRET` is set.

```bash
curl -X POST https://your-domain.com/api/send-message \
  -H "Authorization: Bearer $OUTBOUND_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"chat_id": 123456789, "text": "hello from the bot"}'
```

Body fields: `chat_id` (int or string, required), `text` (string, required,
≤4096 chars), `parse_mode` (optional: `Markdown`, `MarkdownV2`, or `HTML`).
Returns `{"ok": true, "message_id": <int>}` on success.

## Project Layout

```
src/second_brain/
  cli.py            # argparse entrypoint: serve | poll | summarize | index | prompt
  core/             # shared: config, LLM factory, timezone math, logging, Telegram notify, data models
  bot/              # Telegram capture bot: handlers, webhook server, Drive capture, OAuth, /timebox, /search
  summarizer/       # nightly pipeline: dump parsing, PARA-filing agent, Drive client, agent tools
tests/
  bot/              # bot test suite (offline — no Telegram/Drive/DB calls)
  summarizer/       # summarizer test suite (offline — mocked Drive/LLM)
config.yaml         # summarizer's non-secret LLM tuning + seed categories
pyproject.toml      # single package, all deps, dev extra, `second-brain` console script
Dockerfile          # multi-stage build (uv), one image for both `serve` and `summarize`
fly.toml            # Fly.io app config
```

## Configuration

All settings load from environment variables (`.env` locally, Fly secrets in
production) plus `config.yaml` for the summarizer's non-secret LLM tuning.
See `.env.example` for every variable with inline docs and defaults.

### Bot — Telegram & webhook

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | — | Bot token from @BotFather |
| `WEBHOOK_URL` | prod only | — | Public HTTPS base URL |
| `WEBHOOK_PORT` | no | `8443` | 80, 88, 443, or 8443 (Telegram requirement) |
| `WEBHOOK_PATH` | no | `/webhook` | Path prefix for the webhook endpoint |
| `OUTBOUND_API_SECRET` | no | unset (endpoint disabled) | Shared secret for `POST /api/send-message` |
| `LOG_LEVEL` | no | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL |

### Bot — Google OAuth & Drive capture

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | yes | — | OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | no | `""` | OAuth client secret |
| `GOOGLE_REDIRECT_URI` | no | `{WEBHOOK_URL}/oauth/callback` | OAuth callback URL |
| `DATABASE_USER`/`DATABASE_PASSWORD`/`DATABASE_HOST`/`DATABASE_PORT`/`DATABASE_NAME` | prod | — | Postgres connection for per-user token storage |
| `TOKEN_ENCRYPTION_KEY` | yes | — | Fernet key encrypting stored OAuth tokens |
| `DRIVE_FOLDER_NAME` | no | `second_brain_bot/` | Drive inbox folder; daily notes go here as `YYYY-MM-DD.md` |
| `KNOWLEDGE_FOLDER_NAME` / `KNOWLEDGE_FOLDER_ID` | no | `SecondBrain` | Where `/search` reads the organized knowledge base from |
| `DAY_CUTOFF_HOUR` | no | `0` (disabled) | Hour (0-23, in `APP_TIMEZONE`) before which a message files under the previous day |

### Shared — LLM and timezone

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | yes | — | Used by `/timebox`, `/search`, and the summarizer |
| `LLM_MODEL` | no | `deepseek/deepseek-v4-flash` | Model for `/timebox` and `/search` (summarizer's model comes from `config.yaml`) |
| `APP_TIMEZONE` | no | `Asia/Singapore` | IANA timezone for `/timebox` target-day math, `DAY_CUTOFF_HOUR`, and the summarizer's "today"/"yesterday". `TIMEBOX_TIMEZONE` is a deprecated alias, still honored with a warning |

### Timebox (`/timebox`)

`TIMEBOX_CUTOFF_HOUR`, `TIMEBOX_CALENDAR_ID`, `TIMEBOX_DAY_START`/`_DAY_END`,
`TIMEBOX_WORK_START`/`_WORK_END`/`_WORK_END_HARD`, `TIMEBOX_LUNCH`/`_DINNER`/
`_EAT_DURATION`, `TIMEBOX_COMMUTE_MORNING`/`_EVENING`/`_DURATION` — see
`.env.example` for defaults and descriptions.

### Summarizer (nightly `summarize`/`index`/`prompt`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_SERVICE_REFRESH_TOKEN` | yes | `./token.json` | Path to the OAuth token JSON used for Drive access (or set `GOOGLE_TOKEN_JSON` to its content, for CI) |
| `INPUT_DRIVE_FOLDER_ID` | yes | `""` | Drive folder ID holding the bot's `YYYY-MM-DD.md` dumps |
| `VAULT_FOLDER_ID` | yes | `""` | Drive folder ID for the knowledge base. Fallback aliases `OUTPUT_DRIVE_FOLDER_ID`, then `KNOWLEDGE_FOLDER_ID`, are honored with a deprecation warning |
| `SUMMARY_CHAT_ID` | yes | `""` | Telegram chat ID for the run summary / to-do digest. Fallback alias `TELEGRAM_CHAT_ID` |
| `SUMMARIZER_LOG_DIR` | no | `""` (stdout only) | Directory for a per-run debug log file; Fly captures stdout, so leave empty in production |

Non-secrets go in `config.yaml`:

```yaml
llm:
  model: "deepseek/deepseek-v4-flash"
  provider:
    ignore: ["SomeProvider"]
    allow_fallbacks: true
  temperature: 0.5
  max_tokens: 16000

seed_categories:
  - name: "work"
    description: "Work-related tasks, meetings, projects"
```

### Google Cloud & Database Setup

See [DEVELOPMENT.md](DEVELOPMENT.md) for the step-by-step Google Cloud
project setup (Drive + Calendar APIs, OAuth client, scopes) and the Postgres
`user_tokens` table migration.

## Dump File Format

The bot writes messages as HTML-comment-delimited blocks the summarizer
parses:

```markdown
<!-- msg_id: 12345 -->
Had a productive meeting with the design team today.

<!-- msg_id: 12346 -->
Finished reading chapter 5 on replication.
```

## Testing

```bash
.venv/bin/python -m pytest -q
```

The suite is fully offline — no Telegram, Drive, Postgres, or LLM calls.
See [DEVELOPMENT.md](DEVELOPMENT.md) for layout and conventions.

## Docker

```bash
docker build -t second-brain .
docker run --env-file .env -p 8443:8443 second-brain                 # serve (default CMD)
docker run --env-file .env second-brain second-brain summarize --date yesterday
```

## Security

- Never commit `.env`, `token.json`, `client_secret.json`, or
  `service-account.json`
- Keep the bot token and `OUTBOUND_API_SECRET` private — either grants full
  bot impersonation
- `.gitignore`/`.dockerignore` exclude all of the above by default

## Documentation

- [DEVELOPMENT.md](DEVELOPMENT.md) — local setup, running each mode, tests
- [DEPLOY.md](DEPLOY.md) — Fly.io deployment for both the bot and the
  nightly summarizer job
- [CLAUDE.md](CLAUDE.md) — technical reference for AI coding agents
- [CONTEXT.md](CONTEXT.md) — canonical domain terms
- `docs/adr/` — architecture decision records

## License

MIT License

---

Built for capturing ideas in the moment and turning them into a searchable
knowledge base, one message at a time.
