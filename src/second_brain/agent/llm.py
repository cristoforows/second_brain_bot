from __future__ import annotations

from langchain_openai import ChatOpenAI

from second_brain.core.config import Settings

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def create_llm(settings: Settings) -> ChatOpenAI:
    """Create a ChatOpenAI instance pointed at OpenRouter.

    The model and provider routing are configurable via ``config.yaml``.
    The optional ``provider`` block maps directly to OpenRouter's provider
    selection object (order, ignore, allow_fallbacks, etc.).
    """
    if not settings.openrouter_api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file or GitHub secret."
        )
    extra_body: dict = {}
    if settings.llm.provider:
        extra_body["provider"] = settings.llm.provider
    extra_body["include_reasoning"] = False
    return ChatOpenAI(
        model=settings.llm.model,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=_OPENROUTER_BASE_URL,
        extra_body=extra_body,
        request_timeout=1800,
    )
