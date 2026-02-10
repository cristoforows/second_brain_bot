#!/bin/bash
# Helper script to start the webhook server
# For local development with ngrok:
# 1. Install ngrok: https://ngrok.com/download
# 2. Run: ngrok http 8443
# 3. Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
# 4. Update WEBHOOK_URL in .env with the ngrok URL
# 5. Run this script

echo "Starting Telegram bot webhook server..."
echo ""
echo "Make sure you have:"
echo "1. Updated WEBHOOK_URL in .env with your public URL (ngrok URL for local dev)"
echo "2. Started ngrok if running locally: ngrok http 8443"
echo ""

python3 webhook_server.py
