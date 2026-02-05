# Claude.md - AI Agent Context

## Project Mission

This bot collects data from Telegram chats and dumps it into Google Drive for later processing by a specialized second brain service that will filter and group the data.

## Current State

### What's Implemented
- Basic Telegram bot skeleton using `python-telegram-bot` library
- Configuration management with environment variables (.env)
- Logging infrastructure
- Command handlers (/start, /help)
- Message echo functionality (placeholder for data collection)
- Error handling

### What's NOT Implemented
- **Webhook Configuration**: Bot uses polling; needs to switch to webhooks
- **Google Drive Integration**: No Google Drive API integration yet
- **Google OAuth 2.0**: Need to implement OAuth flow for Drive access
- **Authentication Gate**: Bot should refuse to work until user authenticates
- **`/authenticate` Command**: Command to initiate OAuth flow
- **Markdown File Management**: Creating, appending, editing markdown files in Drive
- **Message ID Tracking**: Storing and finding messages by ID for edit operations
- **Edit Message Handler**: Detecting and processing edited messages from webhooks
- **Token Storage**: Per-user OAuth token storage and management
- **Token Refresh**: Automatic refresh of expired tokens

## Architecture Overview

```
Telegram Webhook → Bot (webhook receiver)
    ↓
Message Handler
    ├─→ Check if user authenticated with Google Drive
    │   ├─→ NO: Send authentication prompt
    │   └─→ YES: Continue processing
    ↓
Extract message ID + content
    ↓
Google Drive API (OAuth 2.0)
    ├─→ Find/Create user's markdown file
    ├─→ Append new message
    └─→ Update existing message (if edited)
    ↓
Markdown file in Google Drive
    ↓
[External Service - handles filtering/grouping]
```

### Key Architectural Decisions

**Step 1: Webhook-based Message Reception**
- Bot uses webhooks (not polling) to receive messages
- More efficient and scalable than polling
- Requires public URL/server to receive webhook POSTs

**Step 2: Authentication-First Approach**
- Bot is completely non-functional until user authenticates with Google Drive
- Any message from unauthenticated user → prompt to use /authenticate
- /authenticate command initiates Google OAuth 2.0 flow
- Only after successful OAuth can bot collect messages

## Key Files

### bot.py (lines 1-152)
- Main bot application
- Entry point: `main()` function
- Current handlers: `/start`, `/help`, and text message echo
- Uses `telegram.ext.Application` for bot framework
- **Needs to change**:
  - Switch from `run_polling()` to webhook setup
  - Add authentication gate to all handlers
  - Add `/authenticate` command handler
  - Replace echo handler with message collection + Drive append
  - Add edited_message handler

### config.py (lines 1-86)
- Handles environment variable loading
- Validates bot token format
- Sets up logging configuration
- **Needs to add**:
  - Google OAuth credentials (client_id, client_secret, redirect_uri)
  - Webhook URL and port
  - Drive file settings

### google_auth.py (TO CREATE)
- Handle Google OAuth 2.0 flow
- Functions:
  - `generate_auth_url(user_id)` → returns OAuth URL for user
  - `handle_oauth_callback(code, user_id)` → exchange code for tokens
  - `get_user_token(user_id)` → load user's stored token
  - `is_authenticated(user_id)` → check if user has valid token
  - `refresh_token(user_id)` → refresh expired token

### drive_handler.py (TO CREATE)
- Manage Google Drive operations
- Functions:
  - `get_drive_service(user_id)` → initialize Drive API client with user token
  - `get_or_create_markdown_file(user_id)` → find existing or create new
  - `append_message(user_id, message_id, content, timestamp)` → add message
  - `update_message(user_id, message_id, new_content)` → edit existing message
  - `_parse_markdown_for_message(content, message_id)` → find message in markdown
  - `_format_message_block(message_id, content, timestamp)` → create markdown block

### webhook_server.py (TO CREATE - if using separate server)
- Flask or FastAPI app to receive webhooks
- Endpoints:
  - `POST /webhook/{token}` → receive Telegram updates
  - `GET /oauth/callback` → handle OAuth redirect
- Pass updates to bot handlers

### tokens/ (directory, TO CREATE)
- Store user OAuth tokens
- One file per user: `{user_id}.json`
- Format: `{access_token, refresh_token, expiry, scopes}`
- **Add to .gitignore**

### requirements.txt
- Current: `python-telegram-bot`, `python-dotenv`
- **Needs**: Google Drive libraries + webhook server (Flask/FastAPI)

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

## Next Steps (Implementation Order)

### Phase 1: Google Drive Authentication (Step 2 Priority)
1. **Add Google Drive dependencies** to requirements.txt
2. **Set up Google Cloud Project**:
   - Enable Google Drive API
   - Create OAuth 2.0 credentials (Web application type)
   - Configure redirect URIs
   - Add credentials to .env
3. **Create `google_auth.py` module**:
   - Generate OAuth authorization URL
   - Handle OAuth callback/code exchange
   - Store tokens per user_id in `tokens/` directory
   - Token refresh logic
   - Check if user is authenticated
4. **Create `drive_handler.py` module**:
   - Initialize Drive API client with user token
   - Create/find user's markdown file
   - Download markdown file
   - Append message to markdown content
   - Upload modified file back to Drive
   - Update specific message (for edits)
5. **Add `/authenticate` command** to bot.py:
   - Check if user already authenticated
   - Generate and send OAuth URL
   - Handle callback (may need webhook endpoint)

### Phase 2: Webhook Setup (Step 1 Priority)
6. **Set up webhook infrastructure**:
   - Deploy bot to server with public URL (Heroku, Railway, VPS, etc.)
   - Or use tunneling service (ngrok) for development
   - Configure Flask/FastAPI webhook endpoint
7. **Implement webhook handler**:
   - Receive POST requests from Telegram
   - Parse webhook payload (new message, edited message, etc.)
   - Pass to appropriate handlers
8. **Register webhook with Telegram**:
   - Use `setWebhook` API method
   - URL: `https://your-domain.com/webhook/{bot_token}`

### Phase 3: Message Processing
9. **Implement authentication gate**:
   - Check if user authenticated before processing ANY message
   - If not: send authentication prompt
   - Block all functionality until authenticated
10. **Replace echo handler with message collector**:
    - Extract message_id, text, timestamp, user info
    - Format as markdown block
    - Call drive_handler to append to file
11. **Implement edit message handler**:
    - Listen for "edited_message" webhook event
    - Extract message_id
    - Find and update message in markdown file
    - Upload modified file

### Phase 4: Testing & Refinement
12. **Test authentication flow**: User → /authenticate → OAuth → success
13. **Test message collection**: Send message → appears in Drive markdown
14. **Test message editing**: Edit message → updates in Drive markdown
15. **Test token refresh**: Ensure tokens auto-refresh when expired
16. **Error handling**: Network failures, Drive API errors, token issues

## Technical Decisions Needed

1. **Markdown message format**: Heading style (`## Message ID:`) or comment style (`<!-- msg_id: -->`)?
2. **File naming convention**: Single file or time-based splits? (`second_brain_inbox.md` vs `inbox_2024_02.md`)
3. **Drive folder structure**: Root level or nested folders? (`/SecondBrain/telegram_messages.md`)
4. **OAuth token storage**: File-based per user (`tokens/{user_id}.json`) or database (SQLite)?
5. **Webhook server**: Flask, FastAPI, or built-in python-telegram-bot webhook support?
6. **OAuth callback handling**:
   - Separate web server for callback endpoint?
   - Or use Telegram inline buttons + polling for auth code?
7. **Error handling**: What happens if Drive upload fails? Retry queue? Store locally temporarily?
8. **File size limits**: When to split markdown files? 5MB? 10MB? Monthly?
9. **Edit message handling**: Download entire file or use Drive API partial updates?
10. **Deployment**: Where to host? (Heroku, Railway, DigitalOcean, AWS Lambda)

## Dependencies to Add

```txt
# Google Drive API
google-auth>=2.28.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.116.0

# Webhook server (choose one)
flask>=3.0.0           # Option 1: Flask for webhook endpoint
# OR
fastapi>=0.109.0       # Option 2: FastAPI for webhook endpoint
uvicorn>=0.27.0        # Required for FastAPI

# Already in requirements.txt
python-telegram-bot
python-dotenv
```

## Environment Variables Needed

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
LOG_LEVEL=INFO

# Webhook Configuration
WEBHOOK_URL=https://your-domain.com/webhook  # Public URL for Telegram webhooks
WEBHOOK_PORT=8443  # Port for webhook server (8443, 443, 80, or 88)

# Google Drive OAuth 2.0
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=https://your-domain.com/oauth/callback
# OAuth scopes needed:
# - https://www.googleapis.com/auth/drive.file (create/access bot's own files)

# Storage
TOKEN_STORAGE_PATH=./tokens  # Directory to store user OAuth tokens
DRIVE_FILE_NAME=second_brain_inbox.md  # Name of markdown file in user's Drive

# Optional
MAX_FILE_SIZE_MB=5  # Split markdown file when exceeds this size
```

## Known Issues / TODOs

### Critical (Must Have)
- [ ] Switch from polling to webhooks
- [ ] Implement Google Drive OAuth 2.0 flow
- [ ] Create `/authenticate` command
- [ ] Implement authentication gate (block unauthenticated users)
- [ ] Build markdown file handler (create, append, edit)
- [ ] Store message_id for edit tracking
- [ ] Handle edited_message webhook events
- [ ] Token storage per user (file-based: `tokens/{user_id}.json`)
- [ ] Token refresh logic

### Important (Should Have)
- [ ] Error recovery for failed Drive uploads (retry logic)
- [ ] File size monitoring and splitting
- [ ] Webhook server deployment (choose: Flask/FastAPI)
- [ ] Secure token storage (encryption at rest)
- [ ] Handle OAuth token expiration gracefully
- [ ] Logging for Drive operations
- [ ] User feedback on successful uploads/edits

### Nice to Have
- [ ] Message queue/buffer for offline scenarios
- [ ] Monitoring/metrics for data collection
- [ ] Support for message types beyond text (photos, documents)
- [ ] Delete message handling
- [ ] Search functionality in markdown files
- [ ] Export/download all messages
- [ ] Multiple markdown files per user (by topic/date)

## Message Flow Example

### Scenario 1: Unauthenticated User
```
User: "Hello bot"
Bot: Check authentication → NOT FOUND
Bot: "⚠️ Please authenticate with Google Drive first using /authenticate"

User: "/authenticate"
Bot: Generate OAuth URL
Bot: "Click here to authorize: https://accounts.google.com/o/oauth2/..."
User: Clicks, grants permission
OAuth: Redirect to callback with code
Bot: Exchange code for tokens
Bot: Save tokens to tokens/{user_id}.json
Bot: "✅ Authentication successful! You can now send messages."

User: "Hello bot"
Bot: Check authentication → FOUND
Bot: Process message → Format markdown → Upload to Drive
Bot: "✅ Message saved to your Drive"
```

### Scenario 2: Message Edit
```
User: "Original message"
Bot: Save to Drive as message_id: 12345

User: Edits message to "Updated message"
Telegram: Sends edited_message webhook
Bot: Extract message_id: 12345
Bot: Download markdown file
Bot: Find message with ID 12345
Bot: Replace content
Bot: Upload updated file
Bot: (Optional) "✅ Message updated in Drive"
```

## Development Notes

- Virtual environment: `venv/` (excluded from git)
- Python version: 3.8+
- Bot uses async/await pattern throughout
- Logging configured at module level
- Error handlers catch exceptions at handler level
- Test webhook locally with ngrok before deploying
- Store tokens in `tokens/` directory (add to .gitignore)
- Use environment-specific .env files (.env.development, .env.production)
