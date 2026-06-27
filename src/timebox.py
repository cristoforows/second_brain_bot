"""/timebox conversation: collect next-day tasks and publish a schedule.

Thin Telegram glue only — session state, keyboards, and I/O. All scheduling
judgment lives in scheduler; all calendar I/O lives in calendar_handler.

Flow:
  /timebox -> pick Office/WFH -> (if a schedule already exists for the target
  day) confirm redo -> collect tasks -> /done -> generate -> clear-then-write
  to the Target Calendar -> reply with per-event status.
"""

import asyncio
import logging
from datetime import date, datetime, timezone
from functools import lru_cache

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ReactionEmoji
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import config
from google_auth import has_calendar_scope
import calendar_handler
import scheduler

logger = logging.getLogger(__name__)

CHOOSING_MODE, COLLECTING, CONFIRM_REDO = range(3)
SESSION_TIMEOUT_SECONDS = 30 * 60
_TASKS_KEY = "timebox_tasks"
_MODE_KEY = "timebox_mode"
_DATE_KEY = "timebox_date"

_COLLECT_PROMPT = (
    "Send tomorrow's tasks, one per message — optionally with a duration or "
    'constraint (e.g. "deep work 90m, morning").\n\n'
    "/done - finish and publish your schedule\n"
    "/cancel - abort the session\n\n"
    "Messages in this session are not saved to Drive. "
    "The session expires after 30 minutes of silence."
)


def _day_config() -> scheduler.DayConfig:
    """Build the planner's fixed-block config from environment settings."""
    return scheduler.DayConfig(
        day_start=config.timebox_day_start,
        day_end=config.timebox_day_end,
        lunch=config.timebox_lunch,
        dinner=config.timebox_dinner,
        eat_duration_min=config.timebox_eat_duration,
        commute_morning=config.timebox_commute_morning,
        commute_evening=config.timebox_commute_evening,
        commute_duration_min=config.timebox_commute_duration,
    )


async def start_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /timebox - authenticate, then ask for today's mode."""
    token_storage = context.bot_data.get("token_storage")
    user_id = update.effective_user.id

    # Auth gate doubles as access control for paid LLM calls
    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🏢 Office", callback_data="mode:office"),
            InlineKeyboardButton("🏠 WFH", callback_data="mode:wfh"),
        ]]
    )
    await update.message.reply_text(
        "Timebox session — where are you working today?", reply_markup=keyboard
    )
    logger.info(f"Timebox session started for user {user_id}")
    return CHOOSING_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the Office/WFH choice: pin the target date, check for an existing
    schedule, and either ask to redo or begin collecting."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    token_storage = context.bot_data.get("token_storage")

    mode = query.data.split(":", 1)[1]
    context.user_data[_MODE_KEY] = mode

    target_date = scheduler.compute_target_date(
        datetime.now(timezone.utc), config.timebox_timezone, config.timebox_cutoff_hour
    )
    context.user_data[_DATE_KEY] = target_date

    # No calendar configured -> text-only mode, skip the existence check.
    if not config.timebox_calendar_id:
        context.user_data[_TASKS_KEY] = []
        await query.edit_message_text(f"Mode: {mode}. {_COLLECT_PROMPT}")
        return COLLECTING

    if not has_calendar_scope(user_id, token_storage):
        await query.edit_message_text(
            "Your login predates calendar support. Please re-run /authenticate "
            "to grant Google Calendar access, then start /timebox again."
        )
        return ConversationHandler.END

    service = calendar_handler.get_calendar_service(user_id, token_storage)
    if service is None:
        await query.edit_message_text(
            "Couldn't reach Google Calendar — please re-run /authenticate and try again."
        )
        return ConversationHandler.END

    try:
        exists = await asyncio.to_thread(
            calendar_handler.has_existing_schedule,
            service, config.timebox_calendar_id, target_date, config.timebox_timezone,
        )
    except Exception as e:
        logger.error(f"Calendar existence check failed for user {user_id}: {e}")
        await query.edit_message_text(
            "Couldn't check your calendar right now — please try /timebox again shortly."
        )
        return ConversationHandler.END

    if exists:
        keyboard = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("♻️ Redo", callback_data="redo:yes"),
                InlineKeyboardButton("✋ Keep existing", callback_data="redo:no"),
            ]]
        )
        await query.edit_message_text(
            f"A schedule already exists for {target_date.strftime('%A, %d %b')}. "
            "Redo it (overwrites) or keep the existing one?",
            reply_markup=keyboard,
        )
        return CONFIRM_REDO

    context.user_data[_TASKS_KEY] = []
    await query.edit_message_text(f"Mode: {mode}. {_COLLECT_PROMPT}")
    return COLLECTING


async def confirm_redo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the redo confirmation: keep the existing schedule or collect anew."""
    query = update.callback_query
    await query.answer()

    if query.data == "redo:no":
        await query.edit_message_text("Keeping your existing schedule. Session ended.")
        return ConversationHandler.END

    context.user_data[_TASKS_KEY] = []
    mode = context.user_data.get(_MODE_KEY, "wfh")
    await query.edit_message_text(f"Redoing. Mode: {mode}. {_COLLECT_PROMPT}")
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


def _render_published(result, write_results, target_date: date) -> str:
    """Render the schedule with a ✅/❌ per slot reflecting calendar writes."""
    lines = [f"Timebox for {target_date.strftime('%A, %d %b %Y')}", ""]
    for item, wr in zip(result.schedule, write_results):
        mark = "✅" if wr.ok else "❌"
        line = f"{mark} {item.start}-{item.end}  {item.task}"
        if item.note:
            line += f" ({item.note})"
        lines.append(line)

    failed = sum(1 for wr in write_results if not wr.ok)
    total = len(write_results)
    lines.append("")
    if failed:
        lines.append(f"⚠️ {failed}/{total} events failed — send /done to retry.")
    else:
        lines.append(f"Added {total} events to your calendar.")

    if result.dropped:
        lines.append("")
        lines.append("Dropped:")
        for item in result.dropped:
            lines.append(f"- {item.task} — {item.reason}")
    return "\n".join(lines)


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /done - generate the schedule and publish it to the calendar."""
    tasks = context.user_data.get(_TASKS_KEY) or []
    if not tasks:
        await update.message.reply_text("No tasks collected — timebox session ended.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    mode = context.user_data.get(_MODE_KEY, "wfh")
    target_date = context.user_data.get(_DATE_KEY) or scheduler.compute_target_date(
        datetime.now(timezone.utc), config.timebox_timezone, config.timebox_cutoff_hour
    )

    try:
        # to_thread: the langchain call is sync; don't block the event loop
        result = await asyncio.to_thread(
            scheduler.generate_schedule, tasks, target_date, _llm(), _day_config(), mode
        )
    except scheduler.ScheduleGenerationError:
        logger.error(f"Schedule generation failed twice for user {user_id}")
        # Buffer stays intact; the session stays open so /done retries as-is
        await update.message.reply_text(
            "Scheduling failed — your tasks are still saved. "
            "Send /done again to retry, or /cancel to abort."
        )
        return COLLECTING

    # No calendar configured: reply text only and end.
    if not config.timebox_calendar_id:
        context.user_data.pop(_TASKS_KEY, None)
        await update.message.reply_text(scheduler.render_schedule(result, target_date))
        return ConversationHandler.END

    token_storage = context.bot_data.get("token_storage")
    service = calendar_handler.get_calendar_service(user_id, token_storage)
    if service is None:
        await update.message.reply_text(
            "Schedule is ready but Google Calendar is unreachable — please re-run "
            "/authenticate. Your tasks are kept; send /done to retry.\n\n"
            + scheduler.render_schedule(result, target_date)
        )
        return COLLECTING

    try:
        # Clear-then-write: idempotent regardless of redo or a prior partial /done.
        await asyncio.to_thread(
            calendar_handler.clear_timebox_events,
            service, config.timebox_calendar_id, target_date, config.timebox_timezone,
        )
        write_results = await asyncio.to_thread(
            calendar_handler.write_schedule,
            service, config.timebox_calendar_id, result.schedule, target_date,
            config.timebox_timezone,
        )
    except Exception as e:
        logger.error(f"Calendar publish failed for user {user_id}: {e}")
        await update.message.reply_text(
            "Couldn't publish to your calendar — your tasks are kept. "
            "Send /done to retry, or /cancel to abort.\n\n"
            + scheduler.render_schedule(result, target_date)
        )
        return COLLECTING

    reply = _render_published(result, write_results, target_date)
    if any(not wr.ok for wr in write_results):
        # Keep the buffer open so /done can retry the failed slots (clear-then-write).
        await update.message.reply_text(reply)
        return COLLECTING

    context.user_data.pop(_TASKS_KEY, None)
    await update.message.reply_text(reply)
    logger.info(
        f"Timebox schedule for {target_date} published for user {user_id}: "
        f"{len(write_results)} events, {len(result.dropped)} dropped"
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
            CHOOSING_MODE: [CallbackQueryHandler(choose_mode, pattern=r"^mode:")],
            CONFIRM_REDO: [CallbackQueryHandler(confirm_redo, pattern=r"^redo:")],
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
