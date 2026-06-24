"""/today recap: read back the day's captured notes with an LLM TL;DR.

Read-only counterpart to the capture pipeline — closes the capture→review loop.
Thin Telegram glue; Drive I/O lives in drive_handler, the LLM in scheduler.
"""

import asyncio
import logging
import re
from functools import lru_cache

from telegram import Update
from telegram.ext import ContextTypes

from config import config
import drive_handler
import scheduler

logger = logging.getLogger(__name__)

# Splits a captured file on its message markers (<!-- msg_id: 123 -->).
_BLOCK_RE = re.compile(r"<!-- msg_id: \d+ -->\n")

_SUMMARY_SYSTEM = (
    "You are the user's second-brain assistant. In 1-2 short sentences, "
    "summarize today's captured notes: surface the main themes and any action "
    "items. Be concise and concrete. If the notes are trivial, say so briefly."
)

# Keep the reply under Telegram's hard limit with room for the header/summary.
_MAX_REPLY = 3900


def parse_message_blocks(content: str) -> list[str]:
    """Return captured note texts in order, stripped of the msg_id markers.

    The first split fragment is the file header before any message, so it is
    dropped. Pure function — unit-tested without Drive or config.
    """
    parts = _BLOCK_RE.split(content)
    return [p.strip() for p in parts[1:] if p.strip()]


@lru_cache(maxsize=1)
def _llm():
    return scheduler.create_llm(
        api_key=config.openrouter_api_key, model=config.timebox_llm_model
    )


def _summarize(notes: list[str]) -> str | None:
    """One-paragraph LLM TL;DR of the notes, or None if the call fails."""
    try:
        body = "\n".join(f"- {n}" for n in notes)
        resp = _llm().invoke([("system", _SUMMARY_SYSTEM), ("human", body)])
        text = (getattr(resp, "content", "") or "").strip()
        return text or None
    except Exception as e:
        logger.warning(f"Recap summary failed: {e}")
        return None


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /today - reply with today's captured notes plus an LLM TL;DR."""
    token_storage = context.bot_data.get("token_storage")
    user_id = update.effective_user.id

    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return

    service = drive_handler.get_drive_service(user_id, token_storage)
    if not service:
        await update.message.reply_text(
            "Your Google Drive session expired — please /logout then /authenticate."
        )
        return

    folder_id = drive_handler.get_or_create_folder(service, config.drive_folder_name)
    if not folder_id:
        await update.message.reply_text(
            "Couldn't reach your Drive folder — please try again later."
        )
        return

    file_id = drive_handler.find_daily_file(service, folder_id, config.day_cutoff_hour)
    content = drive_handler.read_file(service, file_id) if file_id else None
    notes = parse_message_blocks(content) if content else []

    if not notes:
        await update.message.reply_text("Nothing captured yet today.")
        return

    # LLM call is sync; keep it off the event loop. Summary is best-effort.
    summary = await asyncio.to_thread(_summarize, notes)

    lines = [f"📋 Today — {len(notes)} note(s)", ""]
    if summary:
        lines += [f"TL;DR: {summary}", ""]
    for n in notes:
        lines.append(f"• {n}")

    reply = "\n".join(lines)
    if len(reply) > _MAX_REPLY:
        reply = reply[:_MAX_REPLY] + "\n…(truncated)"
    await update.message.reply_text(reply)
