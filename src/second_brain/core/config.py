"""Unified application settings for the bot and the summarizer.

One pydantic-settings ``Settings`` model backs both halves of the app. Secrets
and per-deployment values come from the environment / ``.env``; static,
non-secret tuning values (the LLM block, seed categories) come from
``config.yaml``. A module-level ``config`` singleton is constructed eagerly
(mirroring the old bot ``config.py``) so existing bot code can keep doing
``from second_brain.core.config import config`` and reading the same
attribute names it always has. ``get_settings()`` returns that same cached
instance for the summarizer side.

Required-field validation raises a clear ``ValueError`` naming the missing
environment variable(s); the module-level singleton construction below turns
that into a ``SystemExit(1)`` after logging the problem, matching the old
bot's hard-exit-on-missing-config behaviour.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from second_brain.core.models import Category

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # repo root

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_ALLOWED_WEBHOOK_PORTS = {80, 88, 443, 8443}

# env var -> (settings field, default). Env vars listed after the first for a
# given field are deprecated fallbacks: still honored, but logged as such.
_ENV_FALLBACKS: dict[str, list[str]] = {
    "app_timezone": ["APP_TIMEZONE", "TIMEBOX_TIMEZONE"],
    "vault_folder_id": ["VAULT_FOLDER_ID", "OUTPUT_DRIVE_FOLDER_ID", "KNOWLEDGE_FOLDER_ID"],
    "summary_chat_id": ["SUMMARY_CHAT_ID", "TELEGRAM_CHAT_ID"],
}

_TIME_OF_DAY_RE = re.compile(r"^\d{1,2}:\d{2}$")


class LLMConfig(BaseSettings):
    model: str = "deepseek/deepseek-v3.2"
    provider: dict | None = None
    temperature: float = 0.3
    max_tokens: int = 4096


class Settings(BaseSettings):
    """Application settings loaded from .env (secrets) and config.yaml (non-secrets)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ------------------------------------------------------------------
    # Telegram bot
    # ------------------------------------------------------------------
    bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    webhook_url: str = Field(default="", validation_alias="WEBHOOK_URL")
    webhook_port: int = Field(default=8443, validation_alias="WEBHOOK_PORT")
    webhook_path: str = Field(default="/webhook", validation_alias="WEBHOOK_PATH")

    # ------------------------------------------------------------------
    # Google OAuth (bot user-auth flow)
    # ------------------------------------------------------------------
    google_client_id: str = Field(default="", validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", validation_alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="", validation_alias="GOOGLE_REDIRECT_URI")

    # ------------------------------------------------------------------
    # Database (bot token storage)
    # ------------------------------------------------------------------
    database_user: str | None = Field(default=None, validation_alias="DATABASE_USER")
    database_password: str | None = Field(default=None, validation_alias="DATABASE_PASSWORD")
    database_host: str | None = Field(default=None, validation_alias="DATABASE_HOST")
    database_port: str | None = Field(default=None, validation_alias="DATABASE_PORT")
    database_name: str | None = Field(default=None, validation_alias="DATABASE_NAME")

    token_encryption_key: str = Field(default="", validation_alias="TOKEN_ENCRYPTION_KEY")

    # ------------------------------------------------------------------
    # Google Drive (bot capture inbox + knowledge-folder read for /search)
    # ------------------------------------------------------------------
    drive_folder_name: str = Field(default="second_brain_bot/", validation_alias="DRIVE_FOLDER_NAME")
    knowledge_folder_name: str = Field(default="SecondBrain", validation_alias="KNOWLEDGE_FOLDER_NAME")
    knowledge_folder_id: str = Field(default="", validation_alias="KNOWLEDGE_FOLDER_ID")
    day_cutoff_hour: int = Field(default=0, validation_alias="DAY_CUTOFF_HOUR")

    # ------------------------------------------------------------------
    # Outbound send-message endpoint (webhook.py's own POST /api/send-message)
    # ------------------------------------------------------------------
    outbound_api_secret: str | None = Field(default=None, validation_alias="OUTBOUND_API_SECRET")

    # ------------------------------------------------------------------
    # OpenRouter LLM shared by /timebox, /search, and the summarizer
    # ------------------------------------------------------------------
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    llm_model: str = Field(default="deepseek/deepseek-v4-flash", validation_alias="LLM_MODEL")

    # ------------------------------------------------------------------
    # Timebox (/timebox LLM scheduling)
    # ------------------------------------------------------------------
    app_timezone: str = Field(default="Asia/Singapore", validation_alias="APP_TIMEZONE")
    timebox_cutoff_hour: int = Field(default=3, validation_alias="TIMEBOX_CUTOFF_HOUR")
    timebox_calendar_id: str = Field(default="", validation_alias="TIMEBOX_CALENDAR_ID")
    timebox_day_start: str = Field(default="09:00", validation_alias="TIMEBOX_DAY_START")
    timebox_day_end: str = Field(default="23:59", validation_alias="TIMEBOX_DAY_END")
    timebox_work_start: str = Field(default="09:00", validation_alias="TIMEBOX_WORK_START")
    timebox_work_end: str = Field(default="17:00", validation_alias="TIMEBOX_WORK_END")
    timebox_work_end_hard: str = Field(default="18:00", validation_alias="TIMEBOX_WORK_END_HARD")
    timebox_lunch: str = Field(default="12:30", validation_alias="TIMEBOX_LUNCH")
    timebox_dinner: str = Field(default="19:00", validation_alias="TIMEBOX_DINNER")
    timebox_eat_duration: int = Field(default=60, validation_alias="TIMEBOX_EAT_DURATION")
    timebox_commute_morning: str = Field(default="08:00", validation_alias="TIMEBOX_COMMUTE_MORNING")
    timebox_commute_evening: str = Field(default="18:00", validation_alias="TIMEBOX_COMMUTE_EVENING")
    timebox_commute_duration: int = Field(default=45, validation_alias="TIMEBOX_COMMUTE_DURATION")

    # ------------------------------------------------------------------
    # Summarizer (nightly pipeline)
    # ------------------------------------------------------------------
    google_service_refresh_token: str = Field(
        default="./token.json", validation_alias="GOOGLE_SERVICE_REFRESH_TOKEN"
    )
    input_drive_folder_id: str = Field(default="", validation_alias="INPUT_DRIVE_FOLDER_ID")
    vault_folder_id: str = Field(default="", validation_alias="VAULT_FOLDER_ID")
    summary_chat_id: str = Field(default="", validation_alias="SUMMARY_CHAT_ID")
    summarizer_log_dir: str = Field(default="", validation_alias="SUMMARIZER_LOG_DIR")
    # Wall-clock budget for one `summarize` run, enforced with signal.alarm.
    # Default (2100s = 35min) matches the job machine's `timeout -k 60 2100`
    # wrapper, so our own alarm fires first and reports a clean failure
    # instead of the job simply vanishing when the external timeout SIGKILLs it.
    summarizer_max_seconds: int = Field(default=2100, validation_alias="SUMMARIZER_MAX_SECONDS")

    # --- Non-secrets (from config.yaml) ---
    llm: LLMConfig = Field(default_factory=LLMConfig)
    seed_categories: list[Category] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Pre-parse: config.yaml defaults, deprecated-env-var fallbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_config_path() -> Path | None:
        """Find config.yaml, in priority order: SECOND_BRAIN_CONFIG env var,
        then ./config.yaml relative to the current working directory, then
        the repo-root path next to pyproject.toml.

        The repo-root fallback (`Path(__file__).resolve().parents[3]`) only
        resolves correctly for an editable/src-layout install — a
        non-editable install (a wheel unpacked into site-packages) would
        never find it there. `./config.yaml` covers that case: the Docker
        image and any real deployment run `second-brain` from a working
        directory that has `config.yaml` copied alongside it.
        """
        candidates: list[Path] = []
        env_path = os.environ.get("SECOND_BRAIN_CONFIG")
        if env_path:
            candidates.append(Path(env_path))
        candidates.append(Path.cwd() / "config.yaml")
        candidates.append(_PROJECT_ROOT / "config.yaml")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    @model_validator(mode="before")
    @classmethod
    def _load_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        config_path = cls._resolve_config_path()
        if config_path is not None:
            with open(config_path) as f:
                yaml_data = yaml.safe_load(f) or {}
            logger.info(f"Loaded config.yaml from {config_path}")
            # YAML values are defaults; explicit env/init values take precedence
            for key, val in yaml_data.items():
                if key not in values or values[key] is None:
                    values[key] = val
        else:
            logger.info("No config.yaml found (checked SECOND_BRAIN_CONFIG, ./config.yaml, repo root); using LLMConfig defaults")
        return values

    @model_validator(mode="before")
    @classmethod
    def _apply_deprecated_env_fallbacks(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Fill renamed settings from their old env var names when the new
        name isn't set, logging a deprecation warning for the old name."""
        for field_name, env_names in _ENV_FALLBACKS.items():
            if values.get(field_name):
                continue
            primary, *fallbacks = env_names
            if os.environ.get(primary):
                continue
            for env_name in fallbacks:
                raw = os.environ.get(env_name)
                if raw:
                    logger.warning(f"{env_name} is deprecated; use {primary} instead")
                    values[field_name] = raw
                    break
        return values

    # ------------------------------------------------------------------
    # Post-parse validation / derivation
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate_and_derive(self) -> "Settings":
        # --- required fields ---
        required = [
            ("bot_token", "TELEGRAM_BOT_TOKEN"),
            ("google_client_id", "GOOGLE_CLIENT_ID"),
            ("token_encryption_key", "TOKEN_ENCRYPTION_KEY"),
            ("openrouter_api_key", "OPENROUTER_API_KEY"),
        ]
        missing = [env_name for attr, env_name in required if not getattr(self, attr)]
        if missing:
            raise ValueError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )
        if not self._is_valid_token_format(self.bot_token):
            raise ValueError(
                "TELEGRAM_BOT_TOKEN has an invalid format. Token should look like "
                "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
            )
        if self.timebox_calendar_id == "primary":
            raise ValueError("TIMEBOX_CALENDAR_ID must not be 'primary'; use a dedicated calendar")

        # --- soft-validated / derived fields (log + coerce to a safe default) ---
        if self.log_level.upper() not in _VALID_LOG_LEVELS:
            logger.warning(f"Invalid LOG_LEVEL={self.log_level!r}, using INFO")
            self.log_level = "INFO"
        else:
            self.log_level = self.log_level.upper()

        self.webhook_url = self.webhook_url.rstrip("/")
        if not self.webhook_url:
            logger.warning("WEBHOOK_URL not set, webhook mode may not work")

        if self.webhook_port not in _ALLOWED_WEBHOOK_PORTS:
            logger.warning(
                f"Port {self.webhook_port} not in Telegram allowed ports "
                f"{sorted(_ALLOWED_WEBHOOK_PORTS)}, using 8443"
            )
            self.webhook_port = 8443

        if not self.webhook_path.startswith("/"):
            self.webhook_path = f"/{self.webhook_path}"

        if not self.google_redirect_uri:
            self.google_redirect_uri = f"{self.webhook_url}/oauth/callback"

        self.knowledge_folder_id = self.knowledge_folder_id.strip()

        self.day_cutoff_hour = self._validated_hour(
            self.day_cutoff_hour, "DAY_CUTOFF_HOUR", default=0
        )
        self.timebox_cutoff_hour = self._validated_hour(
            self.timebox_cutoff_hour, "TIMEBOX_CUTOFF_HOUR", default=3
        )

        try:
            ZoneInfo(self.app_timezone)
        except Exception:
            logger.warning(f"Invalid APP_TIMEZONE={self.app_timezone!r}, using Asia/Singapore")
            self.app_timezone = "Asia/Singapore"

        for field_name, default in (
            ("timebox_day_start", "09:00"),
            ("timebox_day_end", "23:59"),
            ("timebox_work_start", "09:00"),
            ("timebox_work_end", "17:00"),
            ("timebox_work_end_hard", "18:00"),
            ("timebox_lunch", "12:30"),
            ("timebox_dinner", "19:00"),
            ("timebox_commute_morning", "08:00"),
            ("timebox_commute_evening", "18:00"),
        ):
            setattr(self, field_name, self._validated_time_of_day(field_name, default))

        for field_name, default in (
            ("timebox_eat_duration", 60),
            ("timebox_commute_duration", 45),
        ):
            setattr(self, field_name, self._validated_duration(field_name, default))

        if not self.timebox_calendar_id:
            logger.warning(
                "TIMEBOX_CALENDAR_ID not set — /timebox will reply the schedule "
                "as text only and skip writing to Google Calendar"
            )

        return self

    @staticmethod
    def _is_valid_token_format(token: str) -> bool:
        parts = token.split(":")
        if len(parts) != 2:
            return False
        try:
            int(parts[0])
        except ValueError:
            return False
        return len(parts[1]) >= 20

    def _validated_hour(self, value: int, env_name: str, default: int) -> int:
        if not 0 <= value <= 23:
            logger.warning(f"{env_name}={value} out of range (0-23), using {default}")
            return default
        return value

    def _validated_time_of_day(self, field_name: str, default: str) -> str:
        raw = (getattr(self, field_name) or default).strip() or default
        if _TIME_OF_DAY_RE.match(raw):
            try:
                hh, mm = raw.split(":")
                if 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
                    return f"{int(hh):02d}:{int(mm):02d}"
            except ValueError:
                pass
        logger.warning(f"Invalid {field_name}={raw!r}, using {default}")
        return default

    def _validated_duration(self, field_name: str, default: int) -> int:
        value = getattr(self, field_name)
        if isinstance(value, int) and value > 0:
            return value
        logger.warning(f"Invalid {field_name}={value!r}, using {default}")
        return default

    # ------------------------------------------------------------------
    # Derived properties preserving the bot's original attribute shapes
    # ------------------------------------------------------------------

    @property
    def database_url(self) -> dict[str, str | None]:
        return {
            "username": self.database_user,
            "password": self.database_password,
            "host": self.database_host,
            "port": self.database_port,
            "database": self.database_name,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance, exiting the process with a clear
    message if required configuration is missing or invalid."""
    try:
        return Settings()
    except ValidationError as e:
        for error in e.errors():
            logger.error(f"Configuration error: {error.get('msg', error)}")
        sys.exit(1)


def __getattr__(name: str):
    """Lazily build the `config` singleton on first access (PEP 562).

    `second_brain.cli` dispatches to several subcommands that don't need bot
    credentials at all (summarize/index/prompt) — even `second-brain --help`
    shouldn't require TELEGRAM_BOT_TOKEN etc. just because some other module
    imports this one. Deferring construction to first *attribute* access
    (rather than eagerly at import time, like the old bot's `config.py`)
    means `import second_brain.core.config` alone never validates anything;
    only actually reading `config.<field>` does. `get_settings()` is cached,
    so every caller ends up sharing the same instance regardless of which
    import triggered its construction first.
    """
    if name == "config":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
