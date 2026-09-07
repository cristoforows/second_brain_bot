from __future__ import annotations

import time

import httpx
import structlog

log = structlog.get_logger()

# The outbound webhook runs on a scale-to-zero Fly machine, so the first
# request after an idle period pays a cold-start penalty (machine boot +
# Telegram connection). Give it room, and retry transient failures so a
# single slow call doesn't silently drop the message.
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 2.0


class TelegramService:
    def __init__(
        self,
        outbound_url: str,
        secret: str,
        timeout: float = _DEFAULT_TIMEOUT,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._url = outbound_url
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }

    def send_message(self, chat_id: str, text: str) -> dict:
        """POST {chat_id, text} to the bot endpoint, retrying transient failures.

        Returns the parsed JSON response. Raises the last error if every
        attempt fails.
        """
        payload = {"chat_id": chat_id, "text": text}
        last_exc: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = httpx.post(
                    self._url,
                    json=payload,
                    headers=self._headers,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                log.info("telegram_message_sent", chat_id=chat_id, attempt=attempt)
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                # Don't retry client errors (e.g. 401/400) — they won't fix themselves.
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                last_exc = exc
                if attempt < self._max_attempts:
                    sleep_s = _BACKOFF_BASE ** (attempt - 1)
                    log.warning(
                        "telegram_send_retry",
                        chat_id=chat_id,
                        attempt=attempt,
                        max_attempts=self._max_attempts,
                        error=str(exc),
                        retry_in_s=sleep_s,
                    )
                    time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc
