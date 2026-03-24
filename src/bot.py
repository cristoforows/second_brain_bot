#!/usr/bin/env python3
"""
Telegram Second Brain Bot - Collects messages and saves them to Google Drive.

Authenticates users via Google OAuth 2.0 and stores their messages as markdown
files in their personal Google Drive.
"""

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import config
from google_auth import generate_auth_url, TokenStorage
import drive_handler

# Configure logging
logger = logging.getLogger(__name__)


def _get_token_storage(context: ContextTypes.DEFAULT_TYPE) -> TokenStorage:
    """Get the TokenStorage instance from bot_data."""
    return context.bot_data.get('token_storage')


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    token_storage = _get_token_storage(context)
    user_id = update.effective_user.id
    is_authed = token_storage and token_storage.is_authenticated(user_id)

    if is_authed:
        welcome_message = (
            "Welcome back to Second Brain Bot!\n\n"
            "You are authenticated with Google Drive.\n"
            "Send me any message and I'll save it to your Drive.\n\n"
            "Commands:\n"
            "/status - Check connection status\n"
            "/logout - Disconnect Google Drive\n"
            "/help - Show help"
        )
    else:
        welcome_message = (
            "Welcome to Second Brain Bot!\n\n"
            "I save your Telegram messages to Google Drive as markdown files.\n\n"
            "To get started, authenticate with Google Drive:\n"
            "/authenticate - Connect your Google Drive\n\n"
            "/help - Show help"
        )

    try:
        await update.message.reply_text(welcome_message)
        logger.info(f"Sent welcome message to user {user_id}")
    except Exception as e:
        logger.error(f"Error sending welcome message: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_message = (
        "Second Brain Bot Help\n\n"
        "What I do:\n"
        "I save your Telegram messages to a markdown file in your Google Drive. "
        "Edit a message here and it updates in Drive too.\n\n"
        "Commands:\n"
        "/authenticate - Connect your Google Drive\n"
        "/status - Check connection status\n"
        "/logout - Disconnect Google Drive\n"
        "/help - Show this help message\n\n"
        "How to use:\n"
        "1. Use /authenticate to connect Google Drive\n"
        "2. Send me any text message\n"
        "3. It gets saved to your Drive as markdown\n"
        "4. Edit a message and Drive updates automatically"
    )

    try:
        await update.message.reply_text(help_message)
        logger.info(f"Sent help message to user {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Error sending help message: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


async def authenticate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /authenticate command - initiate OAuth flow."""
    token_storage = _get_token_storage(context)
    user_id = update.effective_user.id

    if not token_storage:
        await update.message.reply_text("Bot is not configured properly. Please contact the administrator.")
        return

    if token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "You are already authenticated with Google Drive.\n"
            "Use /status to check your connection or /logout to disconnect."
        )
        return

    try:
        auth_url = generate_auth_url(
            user_id=user_id,
            client_id=config.google_client_id,
            client_secret=config.google_client_secret,
            redirect_uri=config.google_redirect_uri,
        )
        await update.message.reply_text(
            "Authenticate with Google Drive\n\n"
            f"Click the link below to authorize:\n{auth_url}\n\n"
            "The link expires in 10 minutes."
        )
        logger.info(f"Sent OAuth URL to user {user_id}")
    except Exception as e:
        logger.error(f"Error generating auth URL for user {user_id}: {e}")
        await update.message.reply_text("Failed to generate authentication link. Please try again.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /status command - show authentication and Drive status."""
    token_storage = _get_token_storage(context)
    user_id = update.effective_user.id

    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Not Authenticated\n\n"
            "Use /authenticate to connect your Google Drive."
        )
        return

    token_data = token_storage.get_user_token(user_id)
    expiry_info = "Unknown"
    if token_data and token_data.get('expiry'):
        try:
            expiry = datetime.fromisoformat(token_data['expiry'])
            remaining = expiry - datetime.now(timezone.utc).replace(tzinfo=None)
            hours = int(remaining.total_seconds() // 3600)
            if hours > 0:
                expiry_info = f"{hours} hours"
            else:
                expiry_info = "Token will auto-refresh"
        except (ValueError, TypeError):
            pass

    await update.message.reply_text(
        "Authentication Status\n\n"
        f"Google Drive: Connected\n"
        f"Token expires in: {expiry_info}\n"
        f"Markdown file: {config.drive_folder_name}\n\n"
        "Send any message to save to Drive!"
    )


async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /logout command - remove stored tokens."""
    token_storage = _get_token_storage(context)
    user_id = update.effective_user.id

    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text("You are not currently authenticated.")
        return

    try:
        token_storage.delete_user_token(user_id)
        await update.message.reply_text(
            "Logged out successfully.\n\n"
            "Your authentication has been removed.\n"
            "Use /authenticate to connect again."
        )
        logger.info(f"User {user_id} logged out")
    except Exception as e:
        logger.error(f"Error during logout for user {user_id}: {e}")
        await update.message.reply_text("Failed to log out. Please try again.")


async def store_message_on_drive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save the received message to Google Drive (or handle edits)."""
    token_storage = _get_token_storage(context)
    is_edited = update.edited_message is not None
    message = update.edited_message if is_edited else update.message
    if message is None:
        return

    user_id = update.effective_user.id

    # Authentication gate
    if not token_storage or not token_storage.is_authenticated(user_id):
        await message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return

    user_message = message.text or ""
    message_id = message.message_id
    username = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
    timestamp = message.date or datetime.now(timezone.utc)

    try:
        service = drive_handler.get_drive_service(user_id, token_storage)
        if not service:
            await message.reply_text(
                "Your Google Drive session has expired and could not be refreshed. "
                "Your message was not saved. Please use /logout then /authenticate to reconnect."
            )
            return
        folder_id = drive_handler.get_or_create_folder(service, config.drive_folder_name)
        if not folder_id:
            await message.reply_text(
                "Could not find or create the folder in Google Drive. "
                "Your message was not saved. Please try again later."
            )
            return
        file_id = drive_handler.get_or_create_markdown_file(service, folder_id, config.day_cutoff_hour)
        if not file_id:
            await message.reply_text(
                "Could not find or create the markdown file in Google Drive. "
                "Your message was not saved. Please try again later."
            )
            return

        if is_edited:
            success = drive_handler.update_message(service, file_id, message_id, user_message, timestamp)
            if success:
                logger.info(f"Message {message_id} updated in Drive for user {user_id}")
            else:
                # Message not found for edit - append as new instead
                success = drive_handler.append_message(service, file_id, message_id, user_message, timestamp, username)
                if success:
                    logger.info(f"Edited message {message_id} appended as new for user {user_id}")
        else:
            success = drive_handler.append_message(service, file_id, message_id, user_message, timestamp, username)
            if success:
                logger.info(f"Message {message_id} saved to Drive for user {user_id}")

        if not success:
            if is_edited:
                await message.reply_text(
                    "Failed to update your edited message in Google Drive. "
                    "The change was not saved. Please try again."
                )
            else:
                await message.reply_text(
                    "Failed to save your message to Google Drive. "
                    "Your message was not saved. Please try again."
                )

    except Exception as e:
        logger.error(f"Error saving message for user {user_id}: {e}")
        await message.reply_text(
            "An unexpected error occurred while saving to Google Drive. "
            "Your message was not saved. Please try again later."
        )


async def handle_deleted_message(message_id: int, user_id: int, token_storage: TokenStorage) -> None:
    """Delete a message from Google Drive when it's deleted in Telegram."""
    if not token_storage or not token_storage.is_authenticated(user_id):
        return

    try:
        service = drive_handler.get_drive_service(user_id, token_storage)
        if not service:
            return

        folder_id = drive_handler.get_or_create_folder(service, config.drive_folder_name)
        if not folder_id:
            return

        file_id = drive_handler.get_or_create_markdown_file(service, folder_id, config.day_cutoff_hour)
        if not file_id:
            return

        drive_handler.delete_message(service, file_id, message_id)
        logger.info(f"Deleted message {message_id} from Drive for user {user_id}")

    except Exception as e:
        logger.error(f"Error deleting message {message_id} for user {user_id}: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors that occur during bot operation."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Try to inform the user about the error if possible
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Oops! Something went wrong. The error has been logged and will be fixed soon. 🔧"
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")


def main() -> None:
    """Main function to start the bot."""
    logger.info("Starting Second Brain Bot...")

    try:
        # Create the Application
        application = Application.builder().token(config.bot_token).build()

        # Register command handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("authenticate", authenticate_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("logout", logout_command))

        # Register message handler to save messages to Google Drive
        text_filter = filters.TEXT & ~filters.COMMAND
        application.add_handler(MessageHandler(filters.UpdateType.MESSAGE & text_filter, store_message_on_drive))
        application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & text_filter, store_message_on_drive))

        # Register error handler
        application.add_error_handler(error_handler)

        logger.info("Bot handlers registered successfully")
        logger.info("Starting polling...")

        # Start polling for updates
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True  # Ignore messages received while bot was offline
        )

    except Exception as e:
        logger.critical(f"Failed to start the bot: {e}")
        raise


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        exit(1)