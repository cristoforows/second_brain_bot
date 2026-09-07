from __future__ import annotations

import argparse
import logging
import re
import secrets
import string
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import structlog

from second_brain.agent.agent import build_agent, run_agent, run_agent_index, run_agent_with_prompt
from second_brain.agent.llm import create_llm
from second_brain.core.config import get_settings
from second_brain.core.models import RunResult
from second_brain.core.timeutil import today, yesterday
from second_brain.services.drive import DriveService
from second_brain.services.telegram import TelegramService
from second_brain.tools import drive_tools, telegram_tools
from second_brain.tools.drive_tools import init_tools
from second_brain.utils.parser import parse_dump

log = structlog.get_logger()


_CHECKBOX_RE = re.compile(r"^\s*- \[ \]\s*")
_OBSIDIAN_ANNOTATION_RE = re.compile(r"\s*%%.*?%%")
_TODOIST_LINK_RE = re.compile(r"\s*\[[^\]]*\]\(todoist://[^)]*\)")
_LEGACY_TODOIST_TAG_RE = re.compile(r"\s*#todoist(?:\s+\[.*?\]\(.*?\))?")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _clean_todo_line(line: str) -> str:
    """Strip checkbox, Todoist sync artifacts, and markdown link syntax from a to-do line."""
    line = _CHECKBOX_RE.sub("", line)
    line = _OBSIDIAN_ANNOTATION_RE.sub("", line)
    line = _TODOIST_LINK_RE.sub("", line)
    line = _LEGACY_TODOIST_TAG_RE.sub("", line)
    line = _MARKDOWN_LINK_RE.sub(r"\1", line)
    return line.strip()


def _format_run_summary(date_str: str, message_count: int, updates: list[str]) -> str:
    lines = [f"📝 Second Brain · {date_str}", ""]
    if message_count:
        lines.append(f"📨 {message_count} message{'s' if message_count != 1 else ''} processed")
    else:
        lines.append("🔄 To-do maintenance")
    if updates:
        lines.append("")
        lines.append("Updated:")
        for path in updates:
            lines.append(f"  • {path}")
    elif not message_count:
        lines[-1] += " — nothing changed"
    return "\n".join(lines)


_TODO_BAR = "━━━━━━━━━━━━━━━━━━"


def _format_active_todos(tasks: list[str]) -> str:
    """Build an eye-catching Telegram message from a list of cleaned task strings."""
    if not tasks:
        return f"{_TODO_BAR}\n✅  ALL CLEAR\n{_TODO_BAR}\n\nNothing on your plate — enjoy it! 🎉"

    count = len(tasks)
    lines = [
        f"🚨🚨  {count} TO-DO{'S' if count != 1 else ''} NEED YOU  🚨🚨",
        _TODO_BAR,
        "",
    ]
    for i, task in enumerate(tasks, 1):
        lines.append(f"👉  {i}.  {task}")
        lines.append("")
    lines += [_TODO_BAR, "⚡ Knock these out today — don't let them slip."]
    return "\n".join(lines)


def _get_active_todos(drive: DriveService, output_folder_id: str) -> str | None:
    """Read the to-do file from Drive and return a formatted active task list, or None on failure."""
    try:
        todo_folder = drive.find_file(output_folder_id, "to-do")
        if todo_folder is None:
            return None
        todo_file = drive.find_file(todo_folder["id"], "to-do.md")
        if todo_file is None:
            return None
        content = drive.read_file_raw(todo_file["id"], "to-do/to-do.md")
    except Exception as e:
        log.error("todo_read_failed", error=str(e))
        return None

    tasks = [
        _clean_todo_line(line)
        for line in content.splitlines()
        if _CHECKBOX_RE.match(line)
    ]
    return _format_active_todos(tasks)


def _resolve_date_str(date_str: str | None, tz: str) -> str:
    """Resolve a `--date` value to a concrete `YYYY-MM-DD` string.

    `None` resolves to today in `tz`; the literal `"yesterday"` resolves to
    yesterday in `tz`; any other value (an explicit `YYYY-MM-DD`) passes through.
    """
    if date_str is None:
        return today(tz).isoformat()
    if date_str == "yesterday":
        return yesterday(tz).isoformat()
    return date_str


def _init_agent(dry_run: bool = False) -> tuple:
    """Initialize Drive, tools, and agent. Shared by all pipeline entry points."""
    settings = get_settings()
    drive = DriveService(settings.google_service_refresh_token)
    init_tools(drive, settings.output_drive_folder_id, dry_run=dry_run)
    if settings.telegram_outbound_url and settings.telegram_outbound_secret:
        telegram = TelegramService(settings.telegram_outbound_url, settings.telegram_outbound_secret)
        telegram_tools.init_tools(telegram, settings.telegram_chat_id, dry_run=dry_run)
    llm = create_llm(settings)
    tools = drive_tools.get_all_tools() + telegram_tools.get_all_tools()
    agent = build_agent(llm, tools)
    return settings, drive, agent


def run_pipeline(
    date_str: str | None = None,
    dry_run: bool = False,
    notify: Callable[[str], None] | None = None,
) -> RunResult:
    """Execute the full summarization pipeline for a given date.

    Args:
        date_str: Date string (YYYY-MM-DD), the literal "yesterday", or None.
                  Defaults to today in the configured APP_TIMEZONE.
        dry_run: Skip all Drive write operations when True.
        notify: Callback invoked with each outbound notification message
                (the run summary, then the active to-do list if any). When
                omitted, notifications are sent via Telegram directly, as before.

    Returns:
        A RunResult summarizing what happened during this run.
    """
    start = time.monotonic()
    settings, drive, agent = _init_agent(dry_run=dry_run)
    date_str = _resolve_date_str(date_str, settings.app_timezone)

    def _notify(text: str) -> None:
        if notify is not None:
            notify(text)
        else:
            telegram_tools.send_notification(text)

    log.info("pipeline_start", date=date_str)

    try:
        # --- Find today's dump file ---
        dump_filename = f"{date_str}.md"
        dump_file = drive.find_file(settings.input_drive_folder_id, dump_filename)

        messages = []
        if dump_file is None:
            log.info("no_dump_file_found", filename=dump_filename)
        else:
            log.info("dump_file_found", file_id=dump_file["id"], name=dump_file["name"])
            raw_content = drive.read_file_raw(dump_file["id"], dump_filename)
            messages = parse_dump(raw_content)

        # --- Run agent ---
        if messages:
            log.info("messages_parsed", count=len(messages))
            run_agent(agent, messages)
            log.info("pipeline_complete", date=date_str, messages_processed=len(messages))
            mode = "messages"
        else:
            log.info("no_messages_running_todo_maintenance", date=date_str)
            from second_brain.agent.prompts import TODO_MAINTENANCE_PROMPT
            run_agent_with_prompt(agent, TODO_MAINTENANCE_PROMPT)
            log.info("todo_maintenance_complete", date=date_str)
            mode = "todo_maintenance"

        # --- Send notifications ---
        _notify(_format_run_summary(date_str, len(messages), drive._updates))
        todo_msg = _get_active_todos(drive, settings.output_drive_folder_id)
        if todo_msg:
            _notify(todo_msg)

        return RunResult(
            date=date_str,
            message_count=len(messages),
            updates=list(drive._updates),
            reads=list(drive._reads),
            duration_s=time.monotonic() - start,
            mode=mode,
        )
    finally:
        drive.log_run_summary()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Second Brain Summarizer — organize messages into a living knowledge base",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to process: YYYY-MM-DD, or the literal 'yesterday'. "
        "Defaults to today in APP_TIMEZONE.",
    )
    parser.add_argument(
        "--prompt", "-p",
        type=str,
        default=None,
        help="Run the agent with a custom prompt instead of a dump file.",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Rebuild Directory.yaml files across the knowledge base.",
    )
    parser.add_argument(
        "--changed",
        nargs="+",
        metavar="PATH",
        default=None,
        help="Paths of recently added or modified files (used with --index).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging to see agent reasoning steps.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but skip all Drive write operations.",
    )
    args = parser.parse_args()

    settings = get_settings()
    resolved_date = _resolve_date_str(args.date, settings.app_timezone)

    log_path = _configure_logging(
        verbose=args.verbose, date_str=resolved_date, log_dir=settings.summarizer_log_dir
    )
    if log_path is not None:
        log.info("log_file", path=str(log_path))

    if args.dry_run:
        log.info("dry_run_mode_enabled")
        print("[dry-run] No changes will be written to Google Drive.")

    if args.prompt:
        _run_prompt(args.prompt, dry_run=args.dry_run)
    elif args.index:
        _run_index(args.changed, dry_run=args.dry_run)
    else:
        result = run_pipeline(date_str=resolved_date, dry_run=args.dry_run)
        if result.mode == "messages":
            print(f"Processed {result.message_count} messages from {result.date}.md.")
        else:
            print(f"No messages for {result.date} — ran to-do maintenance.")


def _configure_logging(
    verbose: bool = False, date_str: str | None = None, log_dir: str = "tmp"
) -> Path | None:
    """Configure structlog + stdlib logging.

    Console respects --verbose (INFO by default, DEBUG when set).
    When `log_dir` is non-empty, a DEBUG-level file log is also written to
    ``<log_dir>/<run_id><date>.log`` (relative paths resolve against the
    project root), so local runs leave a per-run trace on disk. An empty
    `log_dir` means stdout-only logging. Returns the log file path, or
    None when no file was written.
    """
    console_level = logging.DEBUG if verbose else logging.INFO

    alphabet = string.ascii_lowercase + string.digits
    run_id = "".join(secrets.choice(alphabet) for _ in range(4))
    date_part = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log_path: Path | None = None
    if log_dir:
        target_dir = Path(log_dir)
        if not target_dir.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            target_dir = project_root / target_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        log_path = target_dir / f"{run_id}{date_part}.log"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processor=structlog.dev.ConsoleRenderer(),
        )
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(console_handler)

    if log_path is not None:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared_processors,
                processor=structlog.dev.ConsoleRenderer(colors=False),
            )
        )
        root.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

    return log_path


def _run_prompt(prompt: str, dry_run: bool = False) -> None:
    """Initialize tools and run the agent with a custom user prompt."""
    _, drive, agent = _init_agent(dry_run=dry_run)
    try:
        run_agent_with_prompt(agent, prompt)
    finally:
        drive.log_run_summary()


def _run_index(changed_files: list[str] | None = None, dry_run: bool = False) -> None:
    """Initialize tools and run the indexer to rebuild Directory.yaml files."""
    _, drive, agent = _init_agent(dry_run=dry_run)
    try:
        run_agent_index(agent, changed_files)
    finally:
        drive.log_run_summary()



if __name__ == "__main__":
    main()
