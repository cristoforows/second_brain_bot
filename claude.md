# Claude.md - AI Agent Context

## Project Mission

This bot collects data from Telegram chats and dumps it into Google Drive for later processing by a specialized second brain service that will filter and group the data.

> **Note:** Source code lives under `src/` (not the repo root). Paths below
> are relative to `src/` unless stated otherwise.

## Current State

### What's Implemented
- Telegram bot using `python-telegram-bot` (v22) with async handlers
- **Two run modes** (share the same handlers via `register_handlers`):
  - `python src/bot.py` → **polling** mode for local development (no public URL)
  - `python src/webhook_server.py` → **Flask webhook** server for production (Fly.dev)
- Google OAuth 2.0 flow with scopes `drive.file` + `calendar.events`
- Authentication gate: unauthenticated users are prompted to `/authenticate`
- Per-user token storage in **PostgreSQL** (encrypted at rest via Fernet), with
  automatic token refresh
- Commands: `/start`, `/help`, `/authenticate`, `/status`, `/logout`, `/timebox`, `/search`
- Message collection → per-day markdown files in the user's Google Drive
  (create / append / edit / delete), with a configurable day-cutoff hour
- `/timebox`: an LLM (OpenRouter via LangChain) turns next-day tasks into a
  timeboxed Schedule, optionally published to a dedicated Google Calendar
- `/search`: an LLM-driven vault agent walks the user's Google Drive knowledge
  folder to answer questions over their notes
- Outbound `POST /api/send-message` endpoint (shared-secret gated)
- Production webhook server runs Flask under `waitress` (a production WSGI
  server, 8 threads) instead of Flask's dev server, and exposes `GET /`
  as an always-on health check used by Fly's `[[http_service.checks]]`

### Known gaps / rough edges
- `.env` files created before the `/timebox` feature lack `OPENROUTER_API_KEY`,
  which is **required** — `config.py` calls `sys.exit(1)` without it
- The OAuth CSRF state cache is in-memory, so a process restart mid-`/authenticate`
  fails the callback (see README "Future Improvements" for the durable options)

## Architecture Overview

```
Telegram ──(prod: webhook POST)──▶ webhook_server.py (Flask)
         └─(local: long polling)──▶ bot.py
                         │ both call register_handlers()
                         ▼
                 Message / command handlers
    ├─→ Auth gate: user has valid Google token in Postgres?
    │   ├─→ NO: prompt /authenticate
    │   └─→ YES: continue
    ↓
    ├─ text message ──▶ drive_handler ──▶ per-day markdown file in Google Drive
    └─ /timebox ──▶ timebox.py ──▶ OpenRouter LLM ──▶ Schedule
                                      └─▶ calendar_handler ──▶ Google Calendar
```

### Key Architectural Decisions
- **Polling for local, webhook for prod** — same handler set, two entrypoints.
  Telegram allows only one delivery method at a time, so switching to local
  polling requires deleting the prod webhook first (and restoring it after).
- **Auth-first** — bot is non-functional until the user completes OAuth.
- **Postgres token storage** (not file-based) — tokens encrypted with Fernet.

## Key Files (under `src/`)

### bot.py
- Local-dev entrypoint: `main()` runs `application.run_polling(...)`
- `register_handlers(application)` — the single source of handler registration,
  reused by the webhook server. Order matters (commands → `/timebox`
  conversation → catch-all text → error handler)
- `store_message_on_drive` handles both new and edited messages;
  `handle_deleted_message` removes them from Drive

### config.py
- Loads/validates env vars: Telegram token, webhook URL/port/path, Google OAuth
  creds, `DATABASE_*`, `TOKEN_ENCRYPTION_KEY`, Drive/day-cutoff, OpenRouter +
  timebox/calendar settings. Hard-exits if required vars are missing

### google_auth.py
- `class TokenStorage` backed by a `psycopg2` connection pool:
  `get_user_token`, `is_authenticated`, `delete_user_token`, save/refresh
- `SCOPES = [drive.file, calendar.events]`
- `generate_auth_url(...)`, `handle_oauth_callback(...)`, `has_calendar_scope(...)`

### drive_handler.py
- `get_drive_service`, `get_or_create_folder`, `get_or_create_markdown_file`
  (per-day file honoring `day_cutoff_hour`), `append_message`,
  `update_message`, `delete_message`

### timebox.py
- `build_timebox_handler()` → the `/timebox` ConversationHandler. Collects tasks,
  calls the OpenRouter LLM to build the Schedule, replies and (optionally) writes
  it to the Target Calendar. See CONTEXT.md for canonical terms

### calendar_handler.py
- Google Calendar writes for the Schedule: tag/list/clear and per-item event creation

### scheduler.py
- Scheduling/slot logic supporting `/timebox` (fixed blocks, office/WFH mode)

### webhook_server.py
- Production entrypoint: Flask app. `POST /webhook/<token>` (Telegram updates,
  incl. deleted-message handling), `GET /oauth/callback` (OAuth redirect),
  `POST /api/send-message` (shared-secret outbound). Builds the bot Application
  and calls `register_handlers`

### Token storage
- PostgreSQL (`DATABASE_*` in `.env`), one row per user, encrypted via Fernet
  (`TOKEN_ENCRYPTION_KEY`). The legacy `tokens/` directory is unused

## Authentication Flows

### Google Drive OAuth 2.0 (CRITICAL - STEP 2)

This is the primary authentication mechanism. Bot is useless without it.

**First-time Setup (Developer)**
1. Create project in Google Cloud Console
2. Enable Google Drive API
3. Create OAuth 2.0 credentials (Web application)
4. Add authorized redirect URIs
5. Store `client_id` and `client_secret` in .env

**User Authentication Flow**
1. User sends any message to bot
2. Bot checks if user has valid Drive OAuth token
3. If NO token:
   - Bot responds: "Please authenticate with Google Drive using /authenticate"
   - Ignores all other commands/messages
4. User sends `/authenticate`
5. Bot generates OAuth authorization URL
6. Bot sends URL to user (click to authorize)
7. User clicks URL → redirected to Google consent screen
8. User grants permissions to bot
9. Google redirects back with authorization code
10. Bot exchanges code for access token + refresh token
11. Bot stores tokens per user_id (database or file)
12. Bot confirms: "Authentication successful! You can now start sending messages."
13. Bot now accepts and processes messages from this user

**Token Management**
- Store tokens per user: `tokens/{user_id}.json`
- Check token validity before each Drive operation
- Automatically refresh expired tokens
- Handle refresh token expiration (re-authenticate required)

**Security Notes**
- Each user has their own OAuth token
- Tokens grant access to user's own Google Drive
- Bot can only access files it creates (or user explicitly shares)
- Scopes: `https://www.googleapis.com/auth/drive.file` (limited to bot-created files)

### Webhook Details (CRITICAL - STEP 1)

**Setting Up Webhooks**
```python
# Set webhook (run once during deployment)
bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
```

**Webhook Events to Handle**
- `message` → New message received
- `edited_message` → Message was edited
- `deleted_message` → Message was deleted (optional)

**Webhook Server Requirements**
- Must use HTTPS (Telegram requirement)
- Valid SSL certificate (Let's Encrypt works)
- Allowed ports: 443, 80, 88, 8443
- Must respond with 200 OK within 60 seconds

**Development Options**
1. Use ngrok for local testing: `ngrok http 8080`
2. Deploy to cloud (Heroku, Railway, Render)
3. Use serverless (AWS Lambda, Google Cloud Functions)

## Data Format - Markdown Files (STEP 1)

### Webhook Message Reception
Bot must be configured to receive webhooks instead of polling:
- Set webhook URL: `https://your-server.com/webhook/{bot_token}`
- Telegram sends POST requests for each update
- Bot processes: new messages, edited messages, deleted messages

### Message Storage in Google Drive

**File Format: Markdown (.md)**
- One markdown file per user in Google Drive
- File name: `telegram_messages_{user_id}.md` or `second_brain_inbox.md`
- Messages are appended in chronological order

**Message Structure**
Each message entry contains:
- **Message ID**: Telegram's unique message_id (for edit tracking)
- **Content**: The actual message text
- **Timestamp**: When message was sent
- **Metadata**: Optional (username, chat_id)

**Example Markdown Format**
```markdown
# Telegram Messages

## Message ID: 12345
**Date:** 2024-02-05 14:30:00
**From:** @username

This is the message content. It can be multiple lines
and include formatting.

---

## Message ID: 12346
**Date:** 2024-02-05 14:35:00
**From:** @username

Another message here.

---
```

**Alternative: Structured Comments Format**
```markdown
<!-- msg_id: 12345 | date: 2024-02-05 14:30:00 | from: @username -->
This is the message content.

<!-- msg_id: 12346 | date: 2024-02-05 14:35:00 | from: @username -->
Another message here.
```

### Handling Message Edits

**When Telegram sends "message edited" webhook:**
1. Extract `message_id` from webhook payload
2. Read markdown file from Google Drive
3. Find the message block with matching ID
4. Replace content in that block
5. Update timestamp to show "Edited: [timestamp]"
6. Upload modified file back to Drive

**Edit Detection in Markdown**
- Parse file to find `## Message ID: {id}` or `<!-- msg_id: {id} -->`
- Replace content between delimiters
- Preserve message ID and structure

### Technical Considerations

**Appending to Markdown Files**
- Download existing file from Drive
- Append new message block
- Re-upload entire file (Drive API doesn't support append-only)
- For large files (>10MB), consider splitting by time period

**File Size Management**
- Monitor file size
- When file exceeds threshold (e.g., 5MB), create new file
- Naming: `second_brain_inbox_2024_02.md`, `second_brain_inbox_2024_03.md`

**Message ID Tracking**
- Keep in-memory cache of recent message IDs → file location
- Speeds up edit operations
- Cache format: `{message_id: (filename, byte_offset)}`

## Development Notes

- Virtual environment: `.venv/` (excluded from git)
- Python version: 3.11
- Bot uses async/await pattern throughout
- Logging configured at module level
- Error handlers catch exceptions at handler level
- Test webhook locally with ngrok before deploying (see DEVELOPMENT.md)
- Token storage is PostgreSQL, not files — the legacy `tokens/` directory is unused
- Run tests with `.venv/bin/python -m pytest -q` (see CI: `.github/workflows/ci.yml`)
