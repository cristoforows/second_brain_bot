from __future__ import annotations

from langchain_openai import ChatOpenAI

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def create_llm(
    api_key: str,
    model: str,
    *,
    timeout: float,
    max_tokens: int | None = None,
    temperature: float | None = None,
    provider: dict | None = None,
) -> ChatOpenAI:
    """Create a ChatOpenAI instance pointed at OpenRouter.

    The only place `ChatOpenAI` is constructed in this codebase. Callers pass
    their own `timeout` (the bot's /timebox and /search use 120s; the
    summarizer's long-running pipeline uses 1800s). `provider`, `max_tokens`,
    and `temperature` are optional — the summarizer passes them from
    `config.yaml`'s `llm` block; the bot's /timebox and /search leave them
    unset.
    """
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file or GitHub secret."
        )
    extra_body: dict = {"include_reasoning": False}
    if provider:
        extra_body["provider"] = provider

    kwargs: dict = dict(
        model=model,
        openai_api_key=api_key,
        openai_api_base=_OPENROUTER_BASE_URL,
        extra_body=extra_body,
        request_timeout=timeout,
    )
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature

    return ChatOpenAI(**kwargs)
