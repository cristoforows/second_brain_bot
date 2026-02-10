#!/usr/bin/env python3
"""
Telegram Echo Bot - A simple bot that echoes messages back to users.

This bot demonstrates basic Telegram bot functionality using the python-telegram-bot library.
It responds to /start and /help commands and echoes all other text messages.
"""

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import config

# Configure logging
logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    welcome_message = (
        "🤖 *Welcome to Echo Bot!*\n\n"
        "I'm a simple bot that echoes everything you send me.\n\n"
        "Try sending me any message and I'll send it right back!\n\n"
        "Available commands:\n"
        "• /start - Show this welcome message\n"
        "• /help - Show help information\n\n"
        "Just start typing to see me in action! 📝"
    )

    try:
        await update.message.reply_text(
            welcome_message,
            parse_mode='Markdown'
        )
        logger.info(f"Sent welcome message to user {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Error sending welcome message: {e}")
        await update.message.reply_text("Sorry, something went wrong! Please try again.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_message = (
        "ℹ️ *Echo Bot Help*\n\n"
        "*What I do:*\n"
        "I'm a simple echo bot that repeats everything you send me.\n\n"
        "*How to use:*\n"
        "1. Send me any text message\n"
        "2. I'll send the exact same message back\n"
        "3. That's it! Simple, right?\n\n"
        "*Available commands:*\n"
        "• /start - Show welcome message\n"
        "• /help - Show this help message\n\n"
        "*Examples:*\n"
        "You: `Hello there!`\n"
        "Me: `Hello there!`\n\n"
        "You: `🎉 Party time!`\n"
        "Me: `🎉 Party time!`\n\n"
        "Have fun chatting with me! 💬"
    )

    try:
        await update.message.reply_text(
            help_message,
            parse_mode='Markdown'
        )
        logger.info(f"Sent help message to user {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Error sending help message: {e}")
        await update.message.reply_text("Sorry, something went wrong! Please try again.")


async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the received message back to the user."""
    try:
        is_edited_message = update.edited_message is not None
        message = update.edited_message if is_edited_message else update.message
        if message is None:
            return

        user_message = message.text or ""
        message_id = message.message_id  # user message_id from Telegram payload
        chat_id = message.chat_id

        reply_message = f"{message_id}: {user_message}"

        # Track mapping: original user message_id -> bot reply message_id (per-chat).
        if is_edited_message:
            # Instead of replying to the edited message, update the bot reply that corresponds
            # to the message_id sent along with the edited_message payload.
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id + 1,
                    text=reply_message,
                )
        else:
            await message.reply_text(reply_message)

    except Exception as e:
        logger.error(f"Error echoing message: {e}")
        try:
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Sorry, I couldn't echo your message. Please try again!"
                )
        except Exception as reply_error:
            logger.error(f"Failed to send error message: {reply_error}")


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
    logger.info("Starting Telegram Echo Bot...")

    try:
        # Create the Application
        application = Application.builder().token(config.bot_token).build()

        # Register command handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))

        # Register message handler for text messages (echo functionality)
        text_filter = filters.TEXT & ~filters.COMMAND
        application.add_handler(MessageHandler(filters.UpdateType.MESSAGE & text_filter, echo_message))
        application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & text_filter, echo_message))

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