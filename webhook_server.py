#!/usr/bin/env python3
"""
Webhook server for Telegram bot using Flask.
Receives webhook updates from Telegram and processes them.
"""

import logging
from flask import Flask, request, Response
from telegram import Update
from telegram.ext import Application
import asyncio
import json

from config import config
from bot import start_command, help_command, echo_message, error_handler

# Configure logging
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Global bot application instance
bot_app: Application = None


async def process_update(update_data: dict) -> None:
    """Process a Telegram update asynchronously."""
    try:
        update = Update.de_json(update_data, bot_app.bot)
        await bot_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)


@app.route('/')
def index():
    """Health check endpoint."""
    return {'status': 'ok', 'message': 'Telegram bot webhook server is running'}


@app.route(f'/webhook/<token>', methods=['POST'])
def webhook(token):
    """Handle incoming webhook updates from Telegram."""
    # Verify the token matches our bot token for security
    if token != config.bot_token:
        logger.warning(f"Webhook called with invalid token: {token[:10]}...")
        return Response(status=403)

    try:
        # Get the update data from Telegram
        update_data = request.get_json(force=True)
        logger.debug(f"Received webhook update: {json.dumps(update_data, indent=2)}")

        # Process the update asynchronously
        asyncio.run(process_update(update_data))

        return Response(status=200)

    except Exception as e:
        logger.error(f"Error in webhook endpoint: {e}", exc_info=True)
        return Response(status=500)


def setup_bot_application() -> Application:
    """Set up and configure the bot application."""
    logger.info("Setting up bot application for webhook mode...")

    # Create the Application
    application = Application.builder().token(config.bot_token).build()

    # Register command handlers
    from telegram.ext import CommandHandler, MessageHandler, filters
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Register message handler for text messages
    text_filter = filters.TEXT & ~filters.COMMAND
    application.add_handler(MessageHandler(filters.UpdateType.MESSAGE & text_filter, echo_message))
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & text_filter, echo_message))

    # Register error handler
    application.add_error_handler(error_handler)

    logger.info("Bot handlers registered successfully")
    return application


async def set_webhook():
    """Set the webhook URL with Telegram."""
    webhook_url = f"{config.webhook_url}{config.webhook_path}/{config.bot_token}"

    logger.info(f"Setting webhook URL: {webhook_url}")

    try:
        await bot_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "edited_message"]
        )

        # Verify webhook was set
        webhook_info = await bot_app.bot.get_webhook_info()
        logger.info(f"Webhook set successfully!")
        logger.info(f"Current webhook URL: {webhook_info.url}")
        logger.info(f"Pending updates: {webhook_info.pending_update_count}")

    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        raise


def main():
    """Main function to start the webhook server."""
    global bot_app

    logger.info("Starting Telegram bot in webhook mode...")

    try:
        # Set up bot application
        bot_app = setup_bot_application()

        # Initialize the bot application
        asyncio.run(bot_app.initialize())

        # Set webhook with Telegram
        asyncio.run(set_webhook())

        # Start Flask server
        logger.info(f"Starting Flask server on port {config.webhook_port}...")
        app.run(
            host='0.0.0.0',
            port=config.webhook_port,
            debug=False  # Set to False in production
        )

    except Exception as e:
        logger.critical(f"Failed to start webhook server: {e}")
        raise


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Webhook server stopped by user")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        exit(1)
