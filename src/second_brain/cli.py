"""Unified CLI: `second-brain <subcommand>`.

Subcommands:
  serve      - run the production webhook server (Flask/waitress)
  poll       - run the bot in local long-polling mode (no public URL needed)
  summarize  - run the nightly summarizer pipeline for one day's dump
  index      - rebuild Directory.yaml files across the knowledge base
  prompt     - run the summarizer agent with an ad-hoc prompt
"""

from __future__ import annotations

import argparse
import logging
import sys

import structlog

from second_brain.core.config import config, get_settings
from second_brain.core.logging import configure_bot_logging, configure_logging
from second_brain.core.notify import send_telegram
from second_brain.summarizer import pipeline

log = structlog.get_logger()

_ERROR_MSG_MAX_LEN = 300


def _cmd_serve(_args: argparse.Namespace) -> int:
    configure_bot_logging(config.log_level)
    logger = logging.getLogger(__name__)
    from second_brain.bot.webhook import serve

    try:
        serve()
    except KeyboardInterrupt:
        logger.info("Webhook server stopped by user")
        return 0
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        return 1
    return 0


def _cmd_poll(_args: argparse.Namespace) -> int:
    configure_bot_logging(config.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Starting Second Brain Bot (polling mode)...")

    from telegram import Update
    from telegram.ext import Application

    from second_brain.bot.handlers import register_handlers

    try:
        application = Application.builder().token(config.bot_token).build()
        # Flag the local polling entrypoint so /status can show a "--local"
        # marker. The webhook server (prod) never sets this.
        application.bot_data["is_local"] = True

        register_handlers(application)
        logger.info("Starting polling...")

        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # Ignore messages received while bot was offline
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        return 0
    except Exception as e:
        logger.critical(f"Failed to start the bot: {e}")
        return 1
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    settings = get_settings()
    resolved_date = pipeline.resolve_date_str(args.date, settings.app_timezone)

    log_path = configure_logging(
        verbose=args.verbose, date_str=resolved_date, log_dir=settings.summarizer_log_dir
    )
    if log_path is not None:
        log.info("log_file", path=str(log_path))

    if args.dry_run:
        log.info("dry_run_mode_enabled")
        print("[dry-run] No changes will be written to Google Drive.")

    try:
        result = pipeline.run_pipeline(date_str=resolved_date, dry_run=args.dry_run)
    except (Exception, KeyboardInterrupt) as e:
        log.exception("summarizer_failed", date=resolved_date)
        if not args.dry_run:
            err_message = str(e)[:_ERROR_MSG_MAX_LEN]
            text = f"❌ Summarizer failed for {resolved_date}: {type(e).__name__}: {err_message}"
            try:
                send_telegram(settings.summary_chat_id, text)
            except Exception:
                log.error("failure_notification_failed", exc_info=True)
        return 1

    if result.mode == "messages":
        print(f"Processed {result.message_count} messages from {result.date}.md.")
    else:
        print(f"No messages for {result.date} — ran to-do maintenance.")
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    settings = get_settings()
    log_path = configure_logging(verbose=args.verbose, log_dir=settings.summarizer_log_dir)
    if log_path is not None:
        log.info("log_file", path=str(log_path))
    if args.dry_run:
        log.info("dry_run_mode_enabled")
        print("[dry-run] No changes will be written to Google Drive.")
    pipeline.run_index(args.changed, dry_run=args.dry_run)
    return 0


def _cmd_prompt(args: argparse.Namespace) -> int:
    settings = get_settings()
    log_path = configure_logging(verbose=args.verbose, log_dir=settings.summarizer_log_dir)
    if log_path is not None:
        log.info("log_file", path=str(log_path))
    if args.dry_run:
        log.info("dry_run_mode_enabled")
        print("[dry-run] No changes will be written to Google Drive.")
    pipeline.run_prompt(args.text, dry_run=args.dry_run)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="second-brain",
        description="Telegram capture bot + AI agent that organizes messages into a living knowledge base",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run the production webhook server")
    serve_parser.set_defaults(func=_cmd_serve)

    poll_parser = subparsers.add_parser("poll", help="Run the bot in local long-polling mode")
    poll_parser.set_defaults(func=_cmd_poll)

    summarize_parser = subparsers.add_parser(
        "summarize", help="Run the nightly summarizer pipeline for one day's dump"
    )
    summarize_parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to process: YYYY-MM-DD, 'yesterday', or 'today'. "
        "Defaults to yesterday in APP_TIMEZONE.",
    )
    summarize_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but skip all Drive writes and Telegram sends.",
    )
    summarize_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging to see agent reasoning steps.",
    )
    summarize_parser.set_defaults(func=_cmd_summarize)

    index_parser = subparsers.add_parser(
        "index", help="Rebuild Directory.yaml files across the knowledge base"
    )
    index_parser.add_argument(
        "--changed",
        nargs="+",
        metavar="PATH",
        default=None,
        help="Paths of recently added or modified files (focuses the reindex).",
    )
    index_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing to Drive.",
    )
    index_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging to see agent reasoning steps.",
    )
    index_parser.set_defaults(func=_cmd_index)

    prompt_parser = subparsers.add_parser(
        "prompt", help="Run the summarizer agent with an ad-hoc prompt"
    )
    prompt_parser.add_argument("text", type=str, help="The prompt to run the agent with.")
    prompt_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing to Drive.",
    )
    prompt_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging to see agent reasoning steps.",
    )
    prompt_parser.set_defaults(func=_cmd_prompt)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
