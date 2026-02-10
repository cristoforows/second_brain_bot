#!/bin/bash
# Script to run bot locally with polling (no ngrok needed)

echo "Starting Telegram bot in POLLING mode (local development)..."
echo "This mode works without a public URL - perfect for testing locally!"
echo ""
echo "Press Ctrl+C to stop the bot"
echo ""

# First, make sure any existing webhook is deleted
echo "Cleaning up any existing webhooks..."
python3 -c "
import asyncio
from telegram import Bot
from config import config

async def delete_webhook():
    bot = Bot(token=config.bot_token)
    await bot.delete_webhook()
    print('Webhook deleted successfully')

asyncio.run(delete_webhook())
"

echo ""
echo "Starting bot with polling..."
python3 bot.py
