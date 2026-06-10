"""/timebox conversation: collect next-day tasks one per message.

Thin Telegram glue only — session state and I/O. All scheduling judgment
lives in the scheduler module.
"""

import asyncio
import logging
from datetime import datetime, timezone
from functools import lru_cache

from telegram import Update
from telegram.constants import ReactionEmoji
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import config
import scheduler

logger = logging.getLogger(__name__)

COLLECTING = 0
SESSION_TIMEOUT_SECONDS = 30 * 60
_TASKS_KEY = "timebox_tasks"


async def start_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /timebox - start a collection session if the user is authenticated."""
    token_storage = context.bot_data.get("token_storage")
    user_id = update.effective_user.id

    # Auth gate doubles as access control for paid LLM calls
    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return ConversationHandler.END

    context.user_data[_TASKS_KEY] = []
    await update.message.reply_text(
        "Timebox session started. Send tomorrow's tasks, one per message — "
        'optionally with a duration or constraint (e.g. "deep work 90m, morning").\n\n'
        "/done - finish and get your schedule\n"
        "/cancel - abort the session\n\n"
        "Messages in this session are not saved to Drive. "
        "The session expires after 30 minutes of silence."
    )
    logger.info(f"Timebox session started for user {user_id}")
    return COLLECTING


async def collect_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Buffer one task message verbatim and acknowledge with a 👍 reaction."""
    context.user_data.setdefault(_TASKS_KEY, []).append(update.message.text)
    await update.message.set_reaction(ReactionEmoji.THUMBS_UP)
    return COLLECTING


@lru_cache(maxsize=1)
def _llm():
    return scheduler.create_llm(
        api_key=config.openrouter_api_key, model=config.timebox_llm_model
    )


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /done - end the session and reply with the generated schedule."""
    tasks = context.user_data.pop(_TASKS_KEY, [])
    if not tasks:
        await update.message.reply_text("No tasks collected — timebox session ended.")
        return ConversationHandler.END

    target_date = scheduler.compute_target_date(
        datetime.now(timezone.utc), config.timebox_timezone, config.timebox_cutoff_hour
    )
    # to_thread: the langchain call is sync; don't block the event loop
    result = await asyncio.to_thread(scheduler.generate_schedule, tasks, target_date, _llm())
    await update.message.reply_text(scheduler.render_schedule(result, target_date))
    logger.info(
        f"Timebox schedule for {target_date} sent to user {update.effective_user.id}: "
        f"{len(result.schedule)} scheduled, {len(result.dropped)} dropped"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel - abort the session and clear the buffer."""
    context.user_data.pop(_TASKS_KEY, None)
    await update.message.reply_text("Timebox session cancelled.")
    return ConversationHandler.END


async def expire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Notify the user when the session times out; the buffer is discarded."""
    context.user_data.pop(_TASKS_KEY, None)
    if update.effective_message:
        await update.effective_message.reply_text(
            "Timebox session expired after 30 minutes of inactivity. "
            "Your messages are saved to Drive as usual again; "
            "send /timebox to start over."
        )
    logger.info(f"Timebox session expired for user {update.effective_user.id}")


def build_timebox_handler() -> ConversationHandler:
    """Build the /timebox ConversationHandler.

    Must be registered before the catch-all save-to-Drive handlers so that
    session messages are diverted from the Drive pipeline. /done and /cancel
    are handled inside the conversation's own states, not as global commands.
    """
    task_message = filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND
    return ConversationHandler(
        entry_points=[CommandHandler("timebox", start_session)],
        states={
            COLLECTING: [
                CommandHandler("done", done),
                CommandHandler("cancel", cancel),
                MessageHandler(task_message, collect_task),
            ],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, expire)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=SESSION_TIMEOUT_SECONDS,
    )
