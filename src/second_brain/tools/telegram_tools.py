from __future__ import annotations

import structlog
from langchain_core.tools import tool

from second_brain.services.telegram import TelegramService

log = structlog.get_logger()

_telegram: TelegramService | None = None
_dry_run: bool = False
_default_chat_id: str = ""


def init_tools(telegram: TelegramService, default_chat_id: str, dry_run: bool = False) -> None:
    global _telegram, _dry_run, _default_chat_id
    _telegram = telegram
    _dry_run = dry_run
    _default_chat_id = default_chat_id


def get_all_tools() -> list:
    if _telegram is None:
        return []
    return [send_telegram_message]


def send_notification(text: str) -> None:
    """Send a message to the default chat_id, silently skipping if Telegram isn't configured."""
    if not _telegram or not _default_chat_id:
        return
    if _dry_run:
        log.info("telegram_notification_dry_run", text=text[:100])
        return
    try:
        _telegram.send_message(_default_chat_id, text)
    except Exception as e:
        log.error("telegram_notification_failed", error=str(e))


@tool
def send_telegram_message(text: str, chat_id: str = "") -> str:
    """Send a message to the user via Telegram.

    Uses the configured default chat_id when chat_id is omitted.

    Args:
        text: The message text to send.
        chat_id: Telegram chat ID to send to. Defaults to the configured recipient.

    Returns a confirmation string, or an error message if the request fails.
    """
    if _telegram is None:
        return "Telegram is not configured."
    target = chat_id or _default_chat_id
    if not target:
        return "No chat_id provided and no default configured."
    if _dry_run:
        return f"[dry-run] would send to {target}: {text}"
    try:
        _telegram.send_message(target, text)
        return f"Message sent to {target}."
    except Exception as e:
        log.error("telegram_send_failed", chat_id=target, error=str(e))
        return f"Failed to send message: {e}"
