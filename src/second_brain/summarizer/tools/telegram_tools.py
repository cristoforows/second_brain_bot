from __future__ import annotations

import structlog
from langchain_core.tools import tool

from second_brain.core.notify import send_telegram

log = structlog.get_logger()

_dry_run: bool = False
_default_chat_id: str = ""
_enabled: bool = False


def init_tools(default_chat_id: str, dry_run: bool = False) -> None:
    """Configure the default notification target.

    Sends go straight through the bot's own Telegram token
    (`second_brain.core.notify`) now that the summarizer runs in the same
    process/image as the bot — there's no separate service to initialize.
    """
    global _dry_run, _default_chat_id, _enabled
    _dry_run = dry_run
    _default_chat_id = default_chat_id
    _enabled = bool(default_chat_id)


def get_all_tools() -> list:
    if not _enabled:
        return []
    return [send_telegram_message]


def send_notification(text: str) -> None:
    """Send a message to the default chat_id, silently skipping if unconfigured."""
    if not _default_chat_id:
        return
    if _dry_run:
        log.info("telegram_notification_dry_run", text=text[:100])
        return
    try:
        send_telegram(_default_chat_id, text)
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
    target = chat_id or _default_chat_id
    if not target:
        return "No chat_id provided and no default configured."
    if _dry_run:
        return f"[dry-run] would send to {target}: {text}"
    try:
        send_telegram(target, text)
        return f"Message sent to {target}."
    except Exception as e:
        log.error("telegram_send_failed", chat_id=target, error=str(e))
        return f"Failed to send message: {e}"
