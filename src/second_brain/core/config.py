from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from second_brain.core.models import Category

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # second_brain_summarizer/


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
    )

    # --- Secrets (from .env) ---
    openrouter_api_key: str = ""
    google_service_refresh_token: str = "./token.json"
    input_drive_folder_id: str = ""
    output_drive_folder_id: str = ""
    telegram_outbound_url: str = ""
    telegram_outbound_secret: str = ""
    telegram_chat_id: str = ""

    # --- Runtime behaviour (env-overridable, sensible defaults) ---
    app_timezone: str = "Asia/Singapore"
    summarizer_log_dir: str = "tmp"

    # --- Non-secrets (from config.yaml) ---
    llm: LLMConfig = Field(default_factory=LLMConfig)
    seed_categories: list[Category] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _load_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        config_path = _PROJECT_ROOT / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                yaml_data = yaml.safe_load(f) or {}
            # YAML values are defaults; explicit env/init values take precedence
            for key, val in yaml_data.items():
                if key not in values or values[key] is None:
                    values[key] = val
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
