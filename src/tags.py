"""/tags and /tag: surface the #hashtags already present in captured notes.

Lightweight organization with zero extra capture effort — hashtags are read
straight out of the notes you already send. Tag extraction and counting are
pure functions so they can be unit-tested without Drive.
"""

import logging
import re
from collections import Counter

from telegram import Update
from telegram.ext import ContextTypes

from config import config
import drive_handler

logger = logging.getLogger(__name__)

_BLOCK_RE = re.compile(r"<!-- msg_id: \d+ -->\n")
# A hashtag: '#' not preceded by a word char, then word chars (must include a letter).
_TAG_RE = re.compile(r"(?<!\w)#(\w*[A-Za-z]\w*)")
_DAILY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

_MAX_FILES = 90       # how many recent daily files to scan
_MAX_HITS = 20        # matches shown for /tag
_SNIPPET_LEN = 160
_MAX_REPLY = 3900


def parse_blocks(content: str) -> list[str]:
    """Captured note texts in order, stripped of the msg_id markers."""
    parts = _BLOCK_RE.split(content)
    return [p.strip() for p in parts[1:] if p.strip()]


def extract_tags(text: str) -> set[str]:
    """Distinct hashtags in `text`, lowercased and without the leading '#'."""
    return {m.group(1).lower() for m in _TAG_RE.finditer(text)}


def count_tags(notes: list[str]) -> Counter:
    """Count how many notes each hashtag appears in (once per note)."""
    counter: Counter = Counter()
    for note in notes:
        for tag in extract_tags(note):
            counter[tag] += 1
    return counter


def _snippet(note: str) -> str:
    one_line = " ".join(note.split())
    if len(one_line) > _SNIPPET_LEN:
        one_line = one_line[:_SNIPPET_LEN].rstrip() + "…"
    return one_line


def _date_of(file_name: str) -> str:
    m = _DAILY_RE.match(file_name)
    return m.group(1) if m else file_name


def _scan(service, folder_id: str):
    """Yield (date, note) for the most recent daily files, newest first."""
    files = drive_handler.list_markdown_files(service, folder_id)
    files = sorted(files, key=lambda f: f.get("name", ""), reverse=True)[:_MAX_FILES]
    for f in files:
        content = drive_handler.read_file(service, f["id"]) or ""
        date = _date_of(f.get("name", ""))
        for note in parse_blocks(content):
            yield date, note


async def _prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auth-gate and resolve (service, folder_id), or reply and return None."""
    token_storage = context.bot_data.get("token_storage")
    user_id = update.effective_user.id
    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return None

    service = drive_handler.get_drive_service(user_id, token_storage)
    if not service:
        await update.message.reply_text(
            "Your Google Drive session expired — please /logout then /authenticate."
        )
        return None

    folder_id = drive_handler.get_or_create_folder(service, config.drive_folder_name)
    if not folder_id:
        await update.message.reply_text(
            "Couldn't reach your Drive folder — please try again later."
        )
        return None
    return service, folder_id


async def tags_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tags - list all hashtags with how many notes use each."""
    prepared = await _prepare(update, context)
    if not prepared:
        return
    service, folder_id = prepared

    counts = count_tags([note for _, note in _scan(service, folder_id)])
    if not counts:
        await update.message.reply_text(
            "No #hashtags found yet. Add #tags to your notes to organize them, "
            "then browse with /tag <name>."
        )
        return

    lines = ["🏷 Tags:"]
    for tag, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"#{tag} ({n})")
    reply = "\n".join(lines)
    if len(reply) > _MAX_REPLY:
        reply = reply[:_MAX_REPLY] + "\n…(truncated)"
    await update.message.reply_text(reply)


async def tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tag <name> - list notes carrying that hashtag."""
    name = (" ".join(context.args).strip().lstrip("#").lower()) if context.args else ""
    if not name:
        await update.message.reply_text("Usage: /tag <name>\ne.g. /tag todo")
        return

    prepared = await _prepare(update, context)
    if not prepared:
        return
    service, folder_id = prepared

    hits = []
    for date, note in _scan(service, folder_id):
        if name in extract_tags(note):
            hits.append((date, _snippet(note)))
            if len(hits) >= _MAX_HITS:
                break

    if not hits:
        await update.message.reply_text(f"No notes tagged #{name}.")
        return

    lines = [f"🏷 #{name} — {len(hits)} note(s):", ""]
    for date, snip in hits:
        lines.append(f"[{date}] {snip}")
    reply = "\n".join(lines)
    if len(reply) > _MAX_REPLY:
        reply = reply[:_MAX_REPLY] + "\n…(truncated)"
    await update.message.reply_text(reply)
