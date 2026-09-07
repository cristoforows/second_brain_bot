"""structlog configuration for the summarizer CLI.

Console output uses a human-readable renderer when stdout is a TTY (local
development); a JSON renderer otherwise, since Fly captures stdout as
structured log lines. An optional per-run debug log file can also be written
locally (see `SUMMARIZER_LOG_DIR` in core.config) — Fly doesn't need this
since it captures stdout directly, so the default is empty (stdout only).
"""

from __future__ import annotations

import logging
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger()


def configure_bot_logging(log_level: str = "INFO") -> None:
    """Configure stdlib logging for the bot's `serve`/`poll` entrypoints.

    Mirrors the old bot `config.py`'s `_setup_logging()`: a plain formatted
    stream handler at `log_level`, with the noisy `httpx`/`telegram` loggers
    turned down.
    """
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, log_level, logging.INFO),
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


def configure_logging(
    verbose: bool = False, date_str: str | None = None, log_dir: str = ""
) -> Path | None:
    """Configure structlog + stdlib logging.

    Console respects `verbose` (INFO by default, DEBUG when set) and renders
    as JSON when stdout is not a TTY, or human-readable text otherwise. When
    `log_dir` is non-empty, a DEBUG-level file log is also written to
    ``<log_dir>/<run_id><date>.log`` (relative paths resolve against the
    project root), so local runs leave a per-run trace on disk. An empty
    `log_dir` means stdout-only logging. Returns the log file path, or None
    when no file was written.
    """
    console_level = logging.DEBUG if verbose else logging.INFO

    alphabet = string.ascii_lowercase + string.digits
    run_id = "".join(secrets.choice(alphabet) for _ in range(4))
    date_part = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log_path: Path | None = None
    if log_dir:
        target_dir = Path(log_dir)
        if not target_dir.is_absolute():
            project_root = Path(__file__).resolve().parents[3]
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

    is_tty = sys.stdout.isatty()
    console_processor = (
        structlog.dev.ConsoleRenderer() if is_tty else structlog.processors.JSONRenderer()
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processor=console_processor,
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
