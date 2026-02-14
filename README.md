# Second Brain Telegram Bot

A Telegram bot that collects your chat messages and stores them in Google Drive for building your personal second brain knowledge base.

## What It Does

This bot acts as your personal data collector:
- Listens to messages you send in Telegram
- Collects and structures your chat data
- Uploads data to your Google Drive
- Data is later processed by specialized services for filtering and organization

Think of it as the first step in building your second brain - capturing everything you communicate in Telegram.

## Current Status

**Functional**: The bot has a working webhook infrastructure, Google OAuth 2.0 authentication, encrypted token storage in PostgreSQL (Supabase), and Google Drive integration for saving and editing messages as markdown files.

## Requirements

- Python 3.8 or higher
- Telegram account
- Google account with Drive API access
- Telegram bot token from @BotFather

## Quick Setup

### 1. Get Your Bot Token

1. Open Telegram and message `@BotFather`
2. Send `/newbot` and follow the instructions
3. Save the bot token you receive

### 2. Install Dependencies

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On macOS/Linux
# venv\Scripts\activate   # On Windows

# Install required packages
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy example configuration
cp .env.example .env

# Edit .env with your credentials
```

Your `.env` file should contain:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
LOG_LEVEL=INFO
```

### 4. Run the Bot

```bash
python bot.py
```

## Usage

- `/start` - Initialize conversation with the bot
- `/help` - Get help information
- `/authenticate` - Connect your Google Drive via OAuth 2.0
- `/status` - Check authentication and Drive connection status
- `/logout` - Disconnect Google Drive and remove stored tokens

Once authenticated, send any text message and it gets saved to a daily markdown file in your Google Drive. Edit a message in Telegram and the Drive file updates automatically.

## Project Structure

```
second_brain_bot/
├── bot.py              # Bot handlers and commands
├── webhook_server.py   # Flask webhook server + OAuth callback endpoint
├── config.py           # Configuration and environment management
├── google_auth.py      # OAuth 2.0 flow, token storage, CSRF protection
├── drive_handler.py    # Google Drive API: file creation, message append/edit
├── requirements.txt    # Python dependencies
├── .env               # Your credentials (create from .env.example)
├── .env.example       # Template for configuration
├── README.md          # This file (user guide)
└── CLAUDE.md          # Technical documentation for AI agents
```

## Configuration

### Environment Variables

- `TELEGRAM_BOT_TOKEN` (required) - Your bot token from @BotFather
- `LOG_LEVEL` (optional) - Set logging verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Google OAuth & Drive Setup

1. Create a project in [Google Cloud Console](https://console.cloud.google.com)
2. Enable the Google Drive API
3. Create OAuth 2.0 credentials (Web application type)
4. Add your redirect URI (e.g. `https://your-domain.com/oauth/callback`)
5. Copy the client ID and client secret to your `.env`

### Database Setup (Supabase)

1. Create a project at [Supabase](https://supabase.com)
2. Run the `CREATE TABLE user_tokens` migration from `authentication_plan.md`
3. Copy the database connection details to your `.env`

### Token Encryption

Generate a Fernet key and add it to your `.env`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Security

- Never commit your `.env` file
- Keep your bot token private
- Don't share OAuth credentials
- The `.gitignore` excludes sensitive files automatically

## Future Improvements

### 1. Stateless Architecture

The OAuth CSRF state cache (`_state_cache` in `google_auth.py`) currently lives in-memory. If the process restarts between a user clicking `/authenticate` and completing the Google consent screen, the callback fails. This also prevents running multiple instances.

**Option A: External KV store (e.g. Cloudflare KV)**
- OAuth state is short-lived (10 min TTL) — KV supports TTL natively
- Access pattern is single-key lookup — KV's strongest use case
- Low volume (only during auth, not per-message)

**Option B: Signed state (no storage needed)**
- Encode `user_id` and `expires_at` into the state string, sign it with `TOKEN_ENCRYPTION_KEY` using HMAC
- The callback validates the signature and expiry without any storage lookup
- Tradeoff: loses one-time-use enforcement, but Google's auth code is already single-use so the practical risk is minimal

### 2. Batched Drive Writes

Currently every message triggers a download-append-upload cycle (2 Drive API calls). For bursts of messages this is wasteful and creates potential race conditions.

**Option A: Time-window buffer**
- Collect messages in a buffer (in-memory, KV, or Redis)
- Flush to Drive after N seconds of inactivity or when buffer hits a size threshold
- Single download + append all + upload per flush
- Risk: messages lost if the process dies mid-buffer; mitigate by buffering in durable storage

**Option B: Pending messages table (more robust)**
- Write each message immediately to a `pending_messages` table in PostgreSQL
- A periodic job (every 30-60s) collects all pending messages per user, downloads the Drive file once, appends all, uploads, then marks them as synced
- Edits update the pending row if not yet synced, or trigger a Drive update if already synced
- Decouples Telegram response time from Drive API latency — the bot can acknowledge instantly

### 3. Media Support (Images, Video, Audio, Files)

Currently only text messages are handled. Supporting media requires a different storage strategy since binary files can't live inline in markdown.

**Approach:**
- Upload media files to a subfolder in the user's Google Drive (e.g. `SecondBrain/media/`)
- Reference them in the markdown by Drive link:
  ```markdown
  <!-- msg_id: 456 -->
  [Photo: sunset.jpg](https://drive.google.com/file/d/abc123/view)
  Caption text here
  ```

**Considerations:**
- **Telegram file download:** `await context.bot.get_file(file_id)` then `.download_as_bytearray()`. Telegram stores files temporarily, so download promptly
- **File size limits:** Telegram Bot API caps file downloads at 20MB
- **Drive upload:** `MediaInMemoryUpload` for small files, `MediaIoBaseUpload` with streaming for larger ones
- **Handler changes:** Broaden filters to include `filters.PHOTO`, `filters.VIDEO`, `filters.AUDIO`, `filters.Document.ALL`. Each type exposes file IDs differently (`message.photo[-1].file_id` for highest-res photo, `message.document.file_id` for documents, etc.)
- **Downstream compatibility:** The markdown format should match what the second brain processing service expects — simple Drive links are the most portable option

### Priority

1. **Batching** — most immediate reliability and performance gain
2. **Stateless** — matters when deploying multiple instances or moving to serverless
3. **Media support** — biggest feature expansion, most implementation work

## Development

See `CLAUDE.md` for technical details, architecture decisions, and implementation roadmap.

## License

MIT License

---

Built for capturing ideas and building a personal knowledge base, one message at a time.
