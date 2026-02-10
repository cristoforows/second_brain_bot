# Development Guide

## Running the Bot with Webhooks (Local Development)

Since Telegram webhooks require a public HTTPS URL, you need to expose your localhost using a tunneling service.

### Option 1: Using ngrok (Recommended for Development)

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
   ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Start the webhook server**
   ```bash
   python3 webhook_server.py
   # Or use the helper script:
   ./start_webhook.sh
   ```

6. **Test the bot**
   - Open Telegram and find your bot
   - Send `/start` command
   - Bot should respond via webhook!

### Option 2: Deploy to a Server

For production or testing without ngrok:

1. Deploy to a server with a public IP (DigitalOcean, AWS, etc.)
2. Set up HTTPS with a valid SSL certificate (Let's Encrypt)
3. Update `WEBHOOK_URL` in .env to your server's URL
4. Run the webhook server

### Switching Back to Polling (Development)

If you want to test locally without ngrok:

```bash
python3 bot.py
```

The original `bot.py` still uses polling mode, which works without a public URL.

## Webhook vs Polling

**Polling (bot.py)**
- ✅ Easy for local development
- ✅ No public URL needed
- ❌ Less efficient (constantly asks Telegram for updates)
- ❌ Higher latency

**Webhooks (webhook_server.py)**
- ✅ More efficient (Telegram pushes updates to you)
- ✅ Lower latency
- ✅ Required for edited message detection
- ❌ Requires public HTTPS URL
- ❌ Needs server setup

## Troubleshooting

### Webhook not receiving updates

1. Check webhook status:
   ```bash
   curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
   ```

2. Verify ngrok is running and URL matches .env

3. Check logs in terminal

### Delete existing webhook

If you need to switch back to polling:
```bash
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/deleteWebhook
```

## Project Structure

```
.
├── bot.py                  # Original bot with polling
├── webhook_server.py       # New webhook server
├── config.py              # Configuration management
├── start_webhook.sh       # Helper script to start webhook server
├── requirements.txt       # Python dependencies
└── .env                   # Environment variables (not in git)
```
