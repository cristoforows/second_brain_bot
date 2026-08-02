#!/usr/bin/env python3
"""
Webhook server for Telegram bot using Flask.
Receives webhook updates from Telegram and processes them.
"""

import logging
import os
from flask import Flask, request, Response, jsonify
from telegram import Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application
import asyncio
import hmac
import json
import threading

from config import config
from bot import register_handlers, handle_deleted_message
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
        if 'deleted_messages' in update_data:
            await _handle_deleted_messages_update(update_data)
            return

        update = Update.de_json(update_data, bot_app.bot)
        await bot_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)


async def _handle_deleted_messages_update(update_data: dict) -> None:
    """Handle a message deletion update from Telegram."""
    # In private chats the chat id is the user id
    chat = update_data.get('chat', {})
    user_id = chat.get('id')
    deleted_messages = update_data.get('deleted_messages', [])

    if not user_id:
        logger.warning("Received deleted_messages update without chat id, skipping")
        return

    for msg in deleted_messages:
        message_id = msg.get('message_id')
        if message_id:
            await handle_deleted_message(message_id, user_id, token_storage)


@app.route('/')
def index():
    """Health check endpoint. Always available — doesn't touch bot_app/token_storage."""
    return {'status': 'ok', 'message': 'Telegram bot webhook server is running'}


def _bot_ready() -> bool:
    """True once bot_app/event_loop/token_storage finished initializing.

    Flask starts accepting connections before this is true (see main()), so
    routes that touch those globals need this guard to fail fast with a
    clean 503 instead of a NoneType error during the brief startup window.
    """
    return bot_app is not None and event_loop is not None and token_storage is not None


@app.route('/oauth/callback')
def oauth_callback():
    """Handle Google OAuth callback redirect."""
    if not _bot_ready():
        return "<h1>Still starting up</h1><p>Please try again in a few seconds.</p>", 503

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


TELEGRAM_MAX_TEXT_LEN = 4096
ALLOWED_PARSE_MODES = {'Markdown', 'MarkdownV2', 'HTML'}


@app.route('/api/send-message', methods=['POST'])
def send_message():
    """Send a Telegram message as the bot. Auth via Authorization: Bearer <secret>.

    A leaked secret grants full bot impersonation — treat it like the bot token.
    """
    if not config.outbound_api_secret:
        return jsonify({'error': 'endpoint disabled'}), 503

    if not _bot_ready():
        return jsonify({'error': 'still starting up, try again shortly'}), 503

    auth_header = request.headers.get('Authorization', '')
    prefix = 'Bearer '
    if not auth_header.startswith(prefix) or not hmac.compare_digest(
        auth_header[len(prefix):], config.outbound_api_secret
    ):
        logger.warning("send-message: invalid or missing Authorization header")
        return jsonify({'error': 'unauthorized'}), 401

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'body must be a JSON object'}), 400

    chat_id = body.get('chat_id')
    if not isinstance(chat_id, (int, str)) or (isinstance(chat_id, str) and not chat_id):
        return jsonify({'error': 'chat_id is required (int or non-empty string)'}), 400

    text = body.get('text')
    if not isinstance(text, str) or not text:
        return jsonify({'error': 'text is required (non-empty string)'}), 400
    if len(text) > TELEGRAM_MAX_TEXT_LEN:
        return jsonify({'error': f'text exceeds {TELEGRAM_MAX_TEXT_LEN} chars'}), 400

    parse_mode = body.get('parse_mode')
    send_kwargs = {'chat_id': chat_id, 'text': text}
    if parse_mode is not None:
        if parse_mode not in ALLOWED_PARSE_MODES:
            return jsonify({'error': f'parse_mode must be one of {sorted(ALLOWED_PARSE_MODES)}'}), 400
        send_kwargs['parse_mode'] = parse_mode

    async def do_send():
        return await bot_app.bot.send_message(**send_kwargs)

    try:
        sent = asyncio.run_coroutine_threadsafe(do_send(), event_loop).result(timeout=10)
        return jsonify({'ok': True, 'message_id': sent.message_id}), 200
    except BadRequest as e:
        logger.warning(f"send-message: Telegram BadRequest: {e}")
        return jsonify({'error': f'telegram bad request: {e}'}), 400
    except Forbidden as e:
        logger.warning(f"send-message: Telegram Forbidden: {e}")
        return jsonify({'error': f'telegram forbidden: {e}'}), 403
    except TelegramError as e:
        logger.error(f"send-message: Telegram error: {e}", exc_info=True)
        return jsonify({'error': f'telegram error: {e}'}), 502
    except Exception as e:
        logger.error(f"send-message: unexpected error: {e}", exc_info=True)
        return jsonify({'error': 'internal error'}), 500


# Must clear the LLM path's own ceiling: scheduler.create_llm sets a 120s
# request timeout and generate_schedule retries once, so /timebox alone can
# legitimately run 240s before it has an answer.
WEBHOOK_PROCESSING_TIMEOUT_SECONDS = 300


def _extract_chat_id(update_data: dict):
    """Best-effort chat id lookup across every update shape this bot handles."""
    try:
        if 'deleted_messages' in update_data:
            return update_data.get('chat', {}).get('id')
        update = Update.de_json(update_data, bot_app.bot)
        return update.effective_chat.id if update and update.effective_chat else None
    except Exception:
        return None


async def _notify_processing_failed(chat_id) -> None:
    """DM the user when we gave up waiting on a webhook update server-side."""
    try:
        await bot_app.bot.send_message(
            chat_id=chat_id,
            text="⚠️ That took too long to process and was stopped. Please try again.",
        )
    except Exception as e:
        logger.error(f"Failed to notify user {chat_id} of processing failure: {e}")


async def _process_update_with_timeout(update_data: dict) -> None:
    """Run process_update on the event loop with its own internal timeout.

    Runs entirely off the Flask thread, so a slow handler never delays our
    HTTP ack to Telegram. Ack'ing late is what caused Telegram to retry
    delivery — running process_update() a second time concurrently with the
    still-in-flight first attempt, which is how /timebox's /done was
    double-writing to Google Calendar. Ack'ing immediately (see webhook())
    removes that incentive for Telegram to retry; this timeout just bounds
    how long we wait before giving up and notifying the user directly.
    """
    try:
        await asyncio.wait_for(process_update(update_data), timeout=WEBHOOK_PROCESSING_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.error(
            f"Webhook processing exceeded {WEBHOOK_PROCESSING_TIMEOUT_SECONDS}s, "
            "giving up and notifying user"
        )
        chat_id = _extract_chat_id(update_data)
        if chat_id is not None:
            await _notify_processing_failed(chat_id)
    except Exception as e:
        logger.error(f"Error in webhook processing: {e}", exc_info=True)


@app.route(f'/webhook/<token>', methods=['POST'])
def webhook(token):
    """Handle incoming webhook updates from Telegram."""
    # Verify the token matches our bot token for security
    if token != config.bot_token:
        logger.warning(f"Webhook called with invalid token: [REDACTED]")
        return Response(status=403)

    if not _bot_ready():
        # Flask accepts connections before bot_app finishes initializing (see
        # main()) — 503 here so Telegram retries shortly instead of getting a
        # raw connection failure during that window.
        logger.warning("Webhook received before bot finished starting up, returning 503")
        return Response(status=503)

    try:
        update_data = request.get_json(force=True)
    except Exception as e:
        logger.error(f"Error parsing webhook payload: {e}", exc_info=True)
        return Response(status=500)

    # Fire-and-forget onto the persistent event loop and ack immediately —
    # do NOT block this thread on the result. See _process_update_with_timeout
    # for why: waiting here is what let Telegram's own delivery timeout race
    # ours and trigger a retry, double-processing the same update.
    asyncio.run_coroutine_threadsafe(_process_update_with_timeout(update_data), event_loop)
    return Response(status=200)


def setup_bot_application() -> Application:
    """Set up and configure the bot application."""
    logger.info("Setting up bot application for webhook mode...")

    # Create the Application
    application = Application.builder().token(config.bot_token).build()

    register_handlers(application)
    return application


async def set_webhook():
    """Set the webhook URL with Telegram."""
    webhook_url = f"{config.webhook_url}{config.webhook_path}/{config.bot_token}"
    redacted_url = f"{config.webhook_url}{config.webhook_path}/[REDACTED]"

    logger.info(f"Setting webhook URL: {redacted_url}")

    try:
        await bot_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "edited_message", "message_delete", "callback_query"]
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


def _run_flask():
    """Run the Flask dev server. Called on its own thread — see main()."""
    app.run(
        host='0.0.0.0',
        port=config.webhook_port,
        debug=False,  # Set to False in production
        use_reloader=False,  # the reloader forks; not compatible with a non-main thread
    )


def main():
    """Main function to start the webhook server.

    Flask starts accepting connections *before* the bot/DB/webhook setup
    below, on its own thread — that setup (Postgres pool, Telegram API round
    trips for initialize/start/setWebhook) took ~2-3s of the machine's cold
    start, during which Fly's proxy was hammering a port nothing was
    listening on yet and giving up. Binding the port first closes that gap;
    routes that need bot_app/event_loop/token_storage guard on _bot_ready()
    for the brief window before this function finishes.
    """
    global bot_app, event_loop, token_storage

    logger.info("Starting Telegram bot in webhook mode...")

    logger.info(f"Starting Flask server on port {config.webhook_port}...")
    flask_thread = threading.Thread(target=_run_flask, daemon=True)
    flask_thread.start()

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

        # Flag local runs so /status shows the "--local" marker, mirroring
        # bot.py's polling entrypoint. Fly injects FLY_APP_NAME on the prod
        # machine; it's absent when running webhook_server.py locally.
        bot_app.bot_data['is_local'] = 'FLY_APP_NAME' not in os.environ

        # Initialize the bot application and set webhook
        asyncio.run_coroutine_threadsafe(bot_app.initialize(), event_loop).result(timeout=10)
        logger.info("Bot application initialized")

        asyncio.run_coroutine_threadsafe(bot_app.start(), event_loop).result(timeout=10)
        logger.info("Bot application started")

        asyncio.run_coroutine_threadsafe(set_webhook(), event_loop).result(timeout=10)

        logger.info("Bot fully initialized and ready to process updates")

        # Flask itself runs on flask_thread; block here so the process stays
        # alive and a crashed Flask thread is noticed instead of running on
        # silently with a dead server.
        while flask_thread.is_alive():
            flask_thread.join(timeout=1)
        logger.critical("Flask server thread exited unexpectedly")

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
