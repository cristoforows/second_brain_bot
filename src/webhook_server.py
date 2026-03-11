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
import threading

from config import config
from bot import start_command, help_command, store_message_on_drive, error_handler, authenticate_command, status_command, logout_command
from google_auth import handle_oauth_callback, TokenStorage

# Configure logging
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Global bot application instance and event loop
bot_app: Application = None
event_loop: asyncio.AbstractEventLoop = None
token_storage: TokenStorage = None


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


@app.route('/oauth/callback')
def oauth_callback():
    """Handle Google OAuth callback redirect."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if error:
        logger.warning(f"OAuth error: {error}")
        return f"<h1>Authentication Failed</h1><p>Error: {error}</p><p>Please try /authenticate again in Telegram.</p>", 400

    if not code or not state:
        return "<h1>Invalid Request</h1><p>Missing code or state parameter.</p>", 400

    user_id = handle_oauth_callback(
        code=code,
        state=state,
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        redirect_uri=config.google_redirect_uri,
        token_storage=token_storage,
    )

    if user_id is None:
        return "<h1>Authentication Failed</h1><p>Invalid or expired state. Please try /authenticate again in Telegram.</p>", 400

    # Send confirmation message to user via Telegram
    async def send_confirmation():
        await bot_app.bot.send_message(
            chat_id=user_id,
            text="Authentication successful! You can now send messages and they will be saved to your Google Drive.",
        )

    try:
        asyncio.run_coroutine_threadsafe(send_confirmation(), event_loop).result(timeout=10)
    except Exception as e:
        logger.error(f"Failed to send confirmation to user {user_id}: {e}")

    return "<h1>Authentication Successful!</h1><p>You can close this window and return to Telegram.</p>"


@app.route(f'/webhook/<token>', methods=['POST'])
def webhook(token):
    """Handle incoming webhook updates from Telegram."""
    # Verify the token matches our bot token for security
    if token != config.bot_token:
        logger.warning(f"Webhook called with invalid token: [REDACTED]")
        return Response(status=403)

    try:
        # Get the update data from Telegram
        update_data = request.get_json(force=True)

        # Process the update asynchronously using the persistent event loop
        future = asyncio.run_coroutine_threadsafe(process_update(update_data), event_loop)
        # Wait for the coroutine to complete (with timeout to prevent hanging)
        future.result(timeout=30)

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
    application.add_handler(CommandHandler("authenticate", authenticate_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("logout", logout_command))

    # Register message handler for text messages
    text_filter = filters.TEXT & ~filters.COMMAND
    application.add_handler(MessageHandler(filters.UpdateType.MESSAGE & text_filter, store_message_on_drive))
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & text_filter, store_message_on_drive))

    # Register error handler
    application.add_error_handler(error_handler)

    logger.info("Bot handlers registered successfully")
    return application


async def set_webhook():
    """Set the webhook URL with Telegram."""
    webhook_url = f"{config.webhook_url}{config.webhook_path}/{config.bot_token}"
    redacted_url = f"{config.webhook_url}{config.webhook_path}/[REDACTED]"

    logger.info(f"Setting webhook URL: {redacted_url}")

    try:
        await bot_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "edited_message"]
        )

        # Verify webhook was set
        webhook_info = await bot_app.bot.get_webhook_info()
        logger.info(f"Webhook set successfully!")
        # Redact token from webhook info URL
        logged_url = webhook_info.url.replace(config.bot_token, "[REDACTED]") if webhook_info.url else "None"
        logger.info(f"Current webhook URL: {logged_url}")
        logger.info(f"Pending updates: {webhook_info.pending_update_count}")

    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        raise


def start_event_loop(loop):
    """Start an event loop in a separate thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def main():
    """Main function to start the webhook server."""
    global bot_app, event_loop, token_storage

    logger.info("Starting Telegram bot in webhook mode...")

    try:
        # Initialize token storage
        token_storage = TokenStorage(config.database_url, config.token_encryption_key)
        logger.info("Token storage initialized")

        # Create a persistent event loop in a separate thread
        event_loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=start_event_loop, args=(event_loop,), daemon=True)
        loop_thread.start()
        logger.info("Event loop started in background thread")

        # Set up bot application
        bot_app = setup_bot_application()

        # Store token_storage in bot_data so handlers can access it
        bot_app.bot_data['token_storage'] = token_storage

        # Initialize the bot application and set webhook
        asyncio.run_coroutine_threadsafe(bot_app.initialize(), event_loop).result(timeout=10)
        logger.info("Bot application initialized")

        asyncio.run_coroutine_threadsafe(bot_app.start(), event_loop).result(timeout=10)
        logger.info("Bot application started")

        asyncio.run_coroutine_threadsafe(set_webhook(), event_loop).result(timeout=10)

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
    finally:
        # Clean up on exit
        if bot_app and event_loop:
            try:
                asyncio.run_coroutine_threadsafe(bot_app.shutdown(), event_loop).result(timeout=5)
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
            event_loop.call_soon_threadsafe(event_loop.stop)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Webhook server stopped by user")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        exit(1)
