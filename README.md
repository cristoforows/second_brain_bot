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

**In Development**: The bot currently has basic Telegram functionality. Google Drive integration and data collection features are being implemented.

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

Currently the bot responds to:
- `/start` - Initialize conversation with the bot
- `/help` - Get help information

Once fully implemented, it will automatically collect and upload your messages to Google Drive.

## Project Structure

```
second_brain_bot/
├── bot.py              # Main bot application
├── config.py           # Configuration and environment management
├── requirements.txt    # Python dependencies
├── .env               # Your credentials (create from .env.example)
├── .env.example       # Template for configuration
├── README.md          # This file (user guide)
└── claude.md          # Technical documentation for AI agents
```

## Configuration

### Environment Variables

- `TELEGRAM_BOT_TOKEN` (required) - Your bot token from @BotFather
- `LOG_LEVEL` (optional) - Set logging verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Google Drive Setup (Coming Soon)

Google Drive integration requires:
- OAuth 2.0 credentials from Google Cloud Console
- Drive API enabled for your project
- Proper redirect URI configuration

Detailed setup instructions will be added once implementation is complete.

## Security

- Never commit your `.env` file
- Keep your bot token private
- Don't share OAuth credentials
- The `.gitignore` excludes sensitive files automatically

## Development

See `claude.md` for technical details, architecture decisions, and implementation roadmap.

## License

MIT License

---

Built for capturing ideas and building a personal knowledge base, one message at a time.
