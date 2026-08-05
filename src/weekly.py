"""/week: an LLM-summarized review of the last 7 days of captured notes.

Higher-altitude counterpart to /today: surfaces recurring themes, action items,
and open loops across the week. Thin Telegram glue — Drive I/O lives in
drive_handler, the LLM in scheduler. File selection and parsing are pure
functions so they can be unit-tested without Drive.
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

_BLOCK_RE = re.compile(r"<!-- msg_id: \d+ -->\n")
_DAILY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

_DAYS = 7
_MAX_REPLY = 3900

_REVIEW_SYSTEM = (
    "You are the user's second-brain weekly reviewer. You receive the notes "
    "they captured over the past week, grouped by day. Produce a concise review "
    "with short bullet points under three headings: Themes (recurring topics), "
    "Action items / open loops, and Highlights. Be specific and skip headings "
    "with nothing to say."
)


def parse_blocks(content: str) -> list[str]:
    """Captured note texts in order, stripped of the msg_id markers."""
    parts = _BLOCK_RE.split(content)
    return [p.strip() for p in parts[1:] if p.strip()]


def select_recent_daily(files: list[dict], days: int = _DAYS) -> list[dict]:
    """Pick the most recent `days` daily files (YYYY-MM-DD.md), newest first.

    Non-daily file names are ignored. Pure — unit-tested without Drive.
    """
    daily = [f for f in files if _DAILY_RE.match(f.get("name", ""))]
    daily.sort(key=lambda f: f["name"], reverse=True)
    return daily[:days]


def build_review_input(days: list[tuple[str, list[str]]]) -> str:
    """Render (date, notes) groups as the human message handed to the LLM."""
    out = []
    for date, notes in days:
        out.append(f"## {date}")
        out.extend(f"- {n}" for n in notes)
        out.append("")
    return "\n".join(out).strip()


@lru_cache(maxsize=1)
def _llm():
    return scheduler.create_llm(
        api_key=config.openrouter_api_key, model=config.timebox_llm_model
    )


def _summarize(days: list[tuple[str, list[str]]]) -> str | None:
    """LLM weekly review of the day-grouped notes, or None if the call fails."""
    try:
        resp = _llm().invoke(
            [("system", _REVIEW_SYSTEM), ("human", build_review_input(days))]
        )
        text = (getattr(resp, "content", "") or "").strip()
        return text or None
    except Exception as e:
        logger.warning(f"Weekly review summary failed: {e}")
        return None


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /week - summarize the notes captured over the last 7 days."""
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

    files = select_recent_daily(drive_handler.list_markdown_files(service, folder_id))
    days: list[tuple[str, list[str]]] = []
    total = 0
    # Oldest-first reads better in the review.
    for f in reversed(files):
        notes = parse_blocks(drive_handler.read_file(service, f["id"]) or "")
        if notes:
            days.append((_DAILY_RE.match(f["name"]).group(1), notes))
            total += len(notes)

    if total == 0:
        await update.message.reply_text("Nothing captured in the last 7 days.")
        return

    summary = await asyncio.to_thread(_summarize, days)

    header = f"🗓 Weekly review — {len(days)} day(s), {total} note(s)"
    if summary:
        reply = f"{header}\n\n{summary}"
    else:
        # LLM unavailable: fall back to a per-day count so the command still helps.
        lines = [header, "", "(summary unavailable — per-day counts:)"]
        lines += [f"• {date}: {len(notes)} note(s)" for date, notes in days]
        reply = "\n".join(lines)

    if len(reply) > _MAX_REPLY:
        reply = reply[:_MAX_REPLY] + "\n…(truncated)"
    await update.message.reply_text(reply)
