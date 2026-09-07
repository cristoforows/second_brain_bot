"""Outbound Telegram notifications for the summarizer.

Replaces the old cross-process HTTP call to the bot's `/api/send-message`
endpoint (`second_brain.summarizer.telegram` / `TelegramService`): now that
the summarizer runs in the same process/image as the bot, it can talk to
Telegram directly with the bot's own token instead of hopping over HTTP.
"""

from __future__ import annotations

import asyncio

import structlog
from telegram import Bot

from second_brain.core.config import config

log = structlog.get_logger()


def send_telegram(chat_id: str, text: str) -> None:
    """Send a Telegram message synchronously using the bot's own token.

    Raises whatever `python-telegram-bot` raises on failure (e.g.
    `telegram.error.TelegramError`) — callers decide whether/how to handle
    that (the summarizer CLI logs and reports it; dry-run skips this call
    entirely).
    """

    async def _send() -> None:
        bot = Bot(token=config.bot_token)
        async with bot:
            await bot.send_message(chat_id=chat_id, text=text)

    asyncio.run(_send())
    log.info("telegram_message_sent", chat_id=chat_id)
