"""/remind: schedule one-off Telegram nudges via the PTB job queue.

Thin Telegram glue. The duration parser is a pure function so it can be
unit-tested without a running bot. Reminders are in-memory (held by the job
queue) and do not survive a process restart — acceptable for a personal bot.
"""

import logging
import re
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# A leading duration token: "30m", "2h", "1d", or a bare number (= minutes).
_DURATION_RE = re.compile(
    r"^(\d+)\s*(s|sec|secs|m|min|mins|h|hr|hrs|d|day|days)?$", re.IGNORECASE
)
_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1,
    "m": 60, "min": 60, "mins": 60,
    "h": 3600, "hr": 3600, "hrs": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}
_MAX_SECONDS = 30 * 86400  # cap reminders at 30 days out

_USAGE = (
    "Usage: /remind <when> <what>\n"
    "e.g. /remind 30m drink water\n"
    "     /remind 2h call the dentist\n"
    "     /remind 1d renew passport\n"
    "(bare number = minutes; units: s, m, h, d)\n\n"
    "/remind list — show pending reminders"
)


def parse_reminder(arg: str) -> tuple[int, str] | None:
    """Parse '<duration> <text>' into (delay_seconds, text), or None if invalid.

    A bare leading number is interpreted as minutes. Returns None when the
    duration is missing/zero/over the cap, or when no reminder text follows.
    """
    arg = (arg or "").strip()
    if not arg:
        return None
    parts = arg.split(maxsplit=1)
    m = _DURATION_RE.match(parts[0])
    if not m:
        return None
    qty = int(m.group(1))
    if qty <= 0:
        return None
    unit = (m.group(2) or "m").lower()
    seconds = qty * _UNIT_SECONDS[unit]
    if seconds > _MAX_SECONDS:
        return None
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return None
    return seconds, text


def humanize(seconds: int) -> str:
    """Render a delay in seconds as a short human phrase (e.g. '2h 30m')."""
    units = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
    out = []
    for label, size in units:
        if seconds >= size:
            out.append(f"{seconds // size}{label}")
            seconds %= size
    return " ".join(out) or "0s"


async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: deliver the reminder text back to the chat."""
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ Reminder: {job.data}")


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remind - schedule a nudge, or list pending ones."""
    token_storage = context.bot_data.get("token_storage")
    user_id = update.effective_user.id
    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return

    arg = " ".join(context.args) if context.args else ""
    if arg.strip().lower() == "list":
        await _list_reminders(update, context)
        return

    parsed = parse_reminder(arg)
    if not parsed:
        await update.message.reply_text(_USAGE)
        return

    if context.job_queue is None:
        await update.message.reply_text(
            "Reminders aren't available right now — please try again later."
        )
        return

    seconds, text = parsed
    chat_id = update.effective_chat.id
    context.job_queue.run_once(
        _fire_reminder, when=seconds, chat_id=chat_id, data=text,
        name=f"reminder:{chat_id}:{update.message.message_id}",
    )
    logger.info(f"Reminder scheduled for user {user_id} in {seconds}s")
    await update.message.reply_text(f"⏰ Got it — I'll remind you in {humanize(seconds)}: {text}")


async def _list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with this chat's pending reminders, soonest first."""
    chat_id = update.effective_chat.id
    if context.job_queue is None:
        await update.message.reply_text("Reminders aren't available right now.")
        return
    jobs = [
        j for j in context.job_queue.jobs()
        if (j.name or "").startswith(f"reminder:{chat_id}:") and j.next_t
    ]
    if not jobs:
        await update.message.reply_text("No pending reminders.")
        return
    jobs.sort(key=lambda j: j.next_t)
    lines = ["⏰ Pending reminders:"]
    for j in jobs:
        lines.append(f"• {j.next_t:%H:%M %d %b} — {j.data}")
    await update.message.reply_text("\n".join(lines))
