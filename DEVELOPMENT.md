# Development Guide

## Running the Bot Locally (Webhooks)

Since Telegram webhooks require a public HTTPS URL, you need to expose your localhost using a tunneling service.

### Option 1: Using ngrok (Recommended)

1. **Install ngrok**
   ```bash
   # macOS
   brew install ngrok

   # Or download from https://ngrok.com/download
   ```

2. **Start ngrok tunnel**
   ```bash
   ngrok http 8443
   ```

   This will output something like:
   ```
   Forwarding    https://abc123.ngrok.io -> http://localhost:8443
   ```

3. **Update your .env file**
   ```env
   WEBHOOK_URL=https://abc123.ngrok.io
   WEBHOOK_PORT=8443
   WEBHOOK_PATH=/webhook
   ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Start the webhook server**
   ```bash
   python3 src/webhook_server.py
   # Or use the helper script:
   ./start_webhook.sh
   ```

6. **Test the bot**
   - Open Telegram and find your bot
   - Send `/start` — bot responds via webhook
   - Send `/authenticate` — bot sends a Google OAuth URL
   - Complete OAuth, then send any message — it gets saved to your Drive

### Option 2: Deploy to a Server

For production or testing without ngrok:

1. Deploy to a server with a public IP (DigitalOcean, AWS, etc.)
2. Set up HTTPS with a valid SSL certificate (Let's Encrypt)
3. Update `WEBHOOK_URL` in `.env` to your server's URL
4. Run `./start_webhook.sh` or `python3 src/webhook_server.py`

See [DEPLOY.md](DEPLOY.md) for full Docker/Kubernetes deployment instructions.

---

## First-Time Setup

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/second_brain_bot.git
cd second_brain_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt   # requirements-dev.txt adds pytest
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env   # Fill in all required values
```

Required `.env` variables:

```env
TELEGRAM_BOT_TOKEN=...
WEBHOOK_URL=https://abc123.ngrok.io
WEBHOOK_PORT=8443
WEBHOOK_PATH=/webhook
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://abc123.ngrok.io/oauth/callback
DATABASE_USER=...
DATABASE_PASSWORD=...
DATABASE_HOST=...
DATABASE_PORT=5432
DATABASE_NAME=second_brain
TOKEN_ENCRYPTION_KEY=...   # generate below
DRIVE_FOLDER_NAME=second_brain_bot/
OPENROUTER_API_KEY=...    # required — /timebox; startup fails without it
```

See `.env.example` for the optional `TIMEBOX_*` settings (LLM model, timezone, calendar ID, fixed daily anchors).

Generate `TOKEN_ENCRYPTION_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Enable **Google Drive API** and **Google Calendar API**: APIs & Services → Library → enable both (Calendar is used by `/timebox`)
4. Create OAuth 2.0 credentials: APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: **Web application**
   - Add authorized redirect URI: `https://your-ngrok-url/oauth/callback`
5. Copy Client ID and Client Secret to `.env`

The bot requests the `drive.file` and `calendar.events` scopes. Tokens minted before calendar support lack the calendar scope — re-run `/authenticate` to upgrade.

### 4. Database Setup (Supabase)

1. Create a project at [Supabase](https://supabase.com)
2. Go to SQL Editor and run:

```sql
CREATE TABLE user_tokens (
    user_id BIGINT PRIMARY KEY,
    encrypted_token TEXT NOT NULL,
    token_expires_at TIMESTAMP,
    last_accessed TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

3. Copy the connection details (host, port, database, user, password) to `.env`

---

## Webhook vs Polling

The bot has **two entrypoints that share the same handlers** (via `register_handlers`):

**Polling (`src/bot.py`)** — local development
- `python3 src/bot.py` (or `./run_local.sh`) long-polls Telegram; no public URL needed
- Best for iterating locally without ngrok

**Webhook (`src/webhook_server.py`)** — production
- `python3 src/webhook_server.py` (or `./start_webhook.sh`) runs the Flask server; Telegram pushes updates via POST
- Requires a public HTTPS URL (ngrok locally, or your deployed domain)

> Telegram allows only **one** delivery method at a time. Switching to local polling deletes the production webhook, so the prod machine stops receiving updates until its webhook is re-set (it re-registers on next start). `run_local.sh` deletes the existing webhook for you before polling.

---

## Troubleshooting

### Webhook not receiving updates

1. Check webhook status:
   ```bash
   curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
   ```

2. Verify ngrok is running and URL in `.env` matches the ngrok URL

3. Check logs:
   ```bash
   python3 src/webhook_server.py
   ```

### Delete existing webhook

To clear a previously registered webhook:
```bash
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/deleteWebhook
```

### OAuth callback fails after bot restart

The OAuth CSRF state cache is in-memory. If the bot restarts between a user clicking `/authenticate` and completing the Google consent screen, the callback will fail with an invalid state error. Ask the user to run `/authenticate` again.

---

## Tests

```bash
pytest            # config is read from pytest.ini (pythonpath=src, testpaths=tests)
```

The suite covers the pure scheduling/calendar logic (`scheduler`, `calendar_handler`) and runs offline — no Telegram, Drive, or LLM calls.

---

## Project Structure

```
second_brain_bot/
├── src/
│   ├── bot.py              # Command handlers + register_handlers; polling entrypoint (local)
│   ├── webhook_server.py   # Flask server: /webhook/<token>, /oauth/callback, / (health), /api/send-message (outbound)
│   ├── config.py           # Loads and validates environment variables
│   ├── google_auth.py      # OAuth 2.0 flow (drive.file + calendar.events), CSRF state, encrypted token storage (PostgreSQL)
│   ├── drive_handler.py    # Google Drive API: create/append/edit markdown files
│   ├── timebox.py          # /timebox conversation (collect tasks → schedule → publish)
│   ├── scheduler.py        # Timebox target-date, LLM schedule generation, rendering
│   └── calendar_handler.py # Google Calendar writes for the schedule
├── tests/                  # pytest suite (scheduler, calendar_handler)
├── k8s/                    # Kubernetes manifests
├── Dockerfile              # Multi-stage build (python:3.11-slim)
├── docker-compose.yml      # Local/small-scale Docker deployment
├── requirements.txt        # Python dependencies
├── start_webhook.sh        # Helper script to start the webhook server
├── run_local.sh            # Helper script for local development
├── .env                    # Your credentials (never commit)
├── .env.example            # Template for .env
├── README.md               # User guide
├── DEVELOPMENT.md          # This file
├── DEPLOY.md               # Docker/Kubernetes deployment guide
└── CLAUDE.md               # Technical documentation for AI agents
```
