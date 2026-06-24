"""/search: keyword search across the captured daily notes in Drive.

Thin Telegram glue. The matching/parsing helpers are pure functions so they
can be unit-tested without Drive. Scans the most recent daily files only, so a
long history stays cheap.
"""

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from config import config
import drive_handler

logger = logging.getLogger(__name__)

_BLOCK_RE = re.compile(r"<!-- msg_id: \d+ -->\n")
_DAILY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

_MAX_FILES = 60      # how many recent daily files to scan
_MAX_HITS = 20       # how many matches to show
_SNIPPET_LEN = 160   # per-hit snippet length
_MAX_REPLY = 3900


def parse_blocks(content: str) -> list[str]:
    """Captured note texts in order, stripped of the msg_id markers."""
    parts = _BLOCK_RE.split(content)
    return [p.strip() for p in parts[1:] if p.strip()]


def find_matches(content: str, query: str) -> list[str]:
    """Notes in `content` that contain `query` (case-insensitive substring)."""
    q = query.lower()
    return [n for n in parse_blocks(content) if q in n.lower()]


def _snippet(note: str) -> str:
    """Collapse a note to a single trimmed line for compact display."""
    one_line = " ".join(note.split())
    if len(one_line) > _SNIPPET_LEN:
        one_line = one_line[:_SNIPPET_LEN].rstrip() + "…"
    return one_line


def _date_of(file_name: str) -> str:
    """The YYYY-MM-DD date encoded in a daily file name, or the raw name."""
    m = _DAILY_RE.match(file_name)
    return m.group(1) if m else file_name


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <query> - find captured notes matching the query."""
    token_storage = context.bot_data.get("token_storage")
    user_id = update.effective_user.id
    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return

    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text("Usage: /search <query>\ne.g. /search dentist")
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

    files = drive_handler.list_markdown_files(service, folder_id)
    # Newest day first; cap the scan so a long history stays cheap.
    files = sorted(files, key=lambda f: f.get("name", ""), reverse=True)[:_MAX_FILES]

    hits: list[tuple[str, str]] = []  # (date, snippet)
    for f in files:
        if len(hits) >= _MAX_HITS:
            break
        content = drive_handler.read_file(service, f["id"]) or ""
        for note in find_matches(content, query):
            hits.append((_date_of(f.get("name", "")), _snippet(note)))
            if len(hits) >= _MAX_HITS:
                break

    if not hits:
        await update.message.reply_text(f'No notes found for "{query}".')
        return

    lines = [f'🔎 {len(hits)} match(es) for "{query}":', ""]
    for d, snip in hits:
        lines.append(f"[{d}] {snip}")
    reply = "\n".join(lines)
    if len(reply) > _MAX_REPLY:
        reply = reply[:_MAX_REPLY] + "\n…(truncated)"
    await update.message.reply_text(reply)
