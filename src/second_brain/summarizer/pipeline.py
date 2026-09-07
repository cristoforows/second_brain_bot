from __future__ import annotations

import re
import time
from collections.abc import Callable

import structlog

from second_brain.core.config import Settings, get_settings
from second_brain.core.llm import create_llm
from second_brain.core.models import RunResult
from second_brain.core.timeutil import today, yesterday
from second_brain.summarizer.agent.agent import build_agent, run_agent, run_agent_index, run_agent_with_prompt
from second_brain.summarizer.drive import DriveService
from second_brain.summarizer.tools import drive_tools, telegram_tools
from second_brain.summarizer.tools.drive_tools import init_tools
from second_brain.summarizer.parser import parse_dump

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


def resolve_date_str(date_str: str | None, tz: str) -> str:
    """Resolve a `--date` value to a concrete `YYYY-MM-DD` string.

    `None` or the literal `"yesterday"` resolves to yesterday in `tz` (the
    nightly job's default target); the literal `"today"` resolves to today in
    `tz`; any other value (an explicit `YYYY-MM-DD`) passes through.
    """
    if date_str is None or date_str == "yesterday":
        return yesterday(tz).isoformat()
    if date_str == "today":
        return today(tz).isoformat()
    return date_str


def _init_agent(settings: Settings, dry_run: bool = False) -> tuple:
    """Initialize Drive, tools, and agent. Shared by all pipeline entry points."""
    drive = DriveService(settings.google_service_refresh_token)
    init_tools(drive, settings.vault_folder_id, dry_run=dry_run)
    telegram_tools.init_tools(settings.summary_chat_id, dry_run=dry_run)
    llm = create_llm(
        settings.openrouter_api_key,
        settings.llm.model,
        timeout=1800,
        max_tokens=settings.llm.max_tokens,
        temperature=settings.llm.temperature,
        provider=settings.llm.provider,
    )
    tools = drive_tools.get_all_tools() + telegram_tools.get_all_tools()
    agent = build_agent(llm, tools)
    return drive, agent


def run_pipeline(
    date_str: str | None = None,
    dry_run: bool = False,
    notify: Callable[[str], None] | None = None,
) -> RunResult:
    """Execute the full summarization pipeline for a given date.

    Args:
        date_str: Date string (YYYY-MM-DD), the literal "yesterday"/"today",
                  or None. Defaults to yesterday in the configured
                  APP_TIMEZONE (the nightly job's target date).
        dry_run: Skip all Drive write operations and Telegram sends when True.
        notify: Callback invoked with each outbound notification message
                (the run summary, then the active to-do list if any). When
                omitted, notifications are sent via Telegram directly, as before.

    Returns:
        A RunResult summarizing what happened during this run.
    """
    start = time.monotonic()
    settings = get_settings()
    drive, agent = _init_agent(settings, dry_run=dry_run)
    date_str = resolve_date_str(date_str, settings.app_timezone)

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
            from second_brain.summarizer.agent.prompts import TODO_MAINTENANCE_PROMPT
            run_agent_with_prompt(agent, TODO_MAINTENANCE_PROMPT)
            log.info("todo_maintenance_complete", date=date_str)
            mode = "todo_maintenance"

        # --- Send notifications ---
        _notify(_format_run_summary(date_str, len(messages), drive._updates))
        todo_msg = _get_active_todos(drive, settings.vault_folder_id)
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


def run_prompt(prompt: str, dry_run: bool = False) -> None:
    """Initialize tools and run the agent with a custom user prompt."""
    settings = get_settings()
    drive, agent = _init_agent(settings, dry_run=dry_run)
    try:
        run_agent_with_prompt(agent, prompt)
    finally:
        drive.log_run_summary()


def run_index(changed_files: list[str] | None = None, dry_run: bool = False) -> None:
    """Initialize tools and run the indexer to rebuild Directory.yaml files."""
    settings = get_settings()
    drive, agent = _init_agent(settings, dry_run=dry_run)
    try:
        run_agent_index(agent, changed_files)
    finally:
        drive.log_run_summary()
