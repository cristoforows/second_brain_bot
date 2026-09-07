"""/search: agentic keyword search over the user's knowledge vault in Drive.

Thin Telegram glue only. All navigation/answering judgment lives in
vault_agent, which lets the LLM walk the vault's folder tree itself via
tools — the vault is written by the external second-brain service in a
nested, cross-linked structure that a flat scan can't handle.
"""

import asyncio
import logging
from functools import lru_cache

from telegram import Update
from telegram.ext import ContextTypes

from config import config
import drive_handler
from google_auth import has_drive_read_scope
import scheduler
import vault_agent

logger = logging.getLogger(__name__)

_MAX_REPLY = 3900


@lru_cache(maxsize=1)
def _llm():
    return scheduler.create_llm(api_key=config.openrouter_api_key, model=config.llm_model)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <query> - agentic search over the user's knowledge vault."""
    token_storage = context.bot_data.get("token_storage")
    user_id = update.effective_user.id
    if not token_storage or not token_storage.is_authenticated(user_id):
        await update.message.reply_text(
            "Please authenticate with Google Drive first using /authenticate"
        )
        return

    if not has_drive_read_scope(user_id, token_storage):
        await update.message.reply_text(
            "Your login predates /search's Drive read access. Please re-run "
            "/authenticate to grant it, then try again."
        )
        return

    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text("Usage: /search <query>\ne.g. /search dentist")
        return

    await update.message.reply_text(f'🔎 Searching for "{query}"...')

    service = drive_handler.get_drive_service(user_id, token_storage)
    if not service:
        await update.message.reply_text(
            "Your Google Drive session expired — please /logout then /authenticate."
        )
        return

    if config.knowledge_folder_id:
        folder_id = config.knowledge_folder_id
        if not drive_handler.verify_folder(service, folder_id):
            await update.message.reply_text(
                "The configured knowledge folder (KNOWLEDGE_FOLDER_ID) isn't "
                "reachable — check the id and that it's shared with this account."
            )
            return
    else:
        folder_id = drive_handler.find_folder(service, config.knowledge_folder_name)
        if not folder_id:
            await update.message.reply_text(
                "No knowledge folder found yet — it's created once the second-brain "
                "service has processed some of your notes."
            )
            return

    try:
        # to_thread: the langchain call is sync; don't block the event loop
        answer = await asyncio.to_thread(
            vault_agent.run_agent, _llm(), service, folder_id, query
        )
    except vault_agent.SearchAgentError:
        logger.error(f"Search agent failed for user {user_id}")
        await update.message.reply_text("Search failed — please try again.")
        return

    if len(answer) > _MAX_REPLY:
        answer = answer[:_MAX_REPLY] + "\n…(truncated)"
    await update.message.reply_text(answer)
    logger.info(f'Search for user {user_id} completed: "{query}"')
