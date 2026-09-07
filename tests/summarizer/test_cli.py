from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from second_brain import cli


_MODULE = "second_brain.cli"


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(date=None, dry_run=False, verbose=False)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.app_timezone = "Asia/Singapore"
    settings.summarizer_log_dir = ""
    settings.summary_chat_id = "chat-1"
    return settings


@patch(f"{_MODULE}.send_telegram")
@patch(f"{_MODULE}.configure_logging")
@patch(f"{_MODULE}.pipeline")
@patch(f"{_MODULE}.get_settings")
def test_summarize_success_returns_zero(mock_get_settings, mock_pipeline, mock_configure_logging, mock_send):
    mock_get_settings.return_value = _make_settings()
    mock_configure_logging.return_value = None
    mock_pipeline.resolve_date_str.return_value = "2026-01-01"
    result = MagicMock(mode="messages", message_count=3, date="2026-01-01")
    mock_pipeline.run_pipeline.return_value = result

    exit_code = cli._cmd_summarize(_args())

    assert exit_code == 0
    mock_send.assert_not_called()


@patch(f"{_MODULE}.send_telegram")
@patch(f"{_MODULE}.configure_logging")
@patch(f"{_MODULE}.pipeline")
@patch(f"{_MODULE}.get_settings")
def test_summarize_failure_sends_telegram_notice_and_returns_one(
    mock_get_settings, mock_pipeline, mock_configure_logging, mock_send
):
    mock_get_settings.return_value = _make_settings()
    mock_configure_logging.return_value = None
    mock_pipeline.resolve_date_str.return_value = "2026-01-01"
    mock_pipeline.run_pipeline.side_effect = RuntimeError("boom")

    exit_code = cli._cmd_summarize(_args())

    assert exit_code == 1
    mock_send.assert_called_once()
    chat_id, text = mock_send.call_args[0]
    assert chat_id == "chat-1"
    assert "2026-01-01" in text
    assert "RuntimeError" in text
    assert "boom" in text
    assert text.startswith("❌ Summarizer failed for")


@patch(f"{_MODULE}.send_telegram")
@patch(f"{_MODULE}.configure_logging")
@patch(f"{_MODULE}.pipeline")
@patch(f"{_MODULE}.get_settings")
def test_summarize_failure_in_dry_run_skips_telegram_notice(
    mock_get_settings, mock_pipeline, mock_configure_logging, mock_send
):
    mock_get_settings.return_value = _make_settings()
    mock_configure_logging.return_value = None
    mock_pipeline.resolve_date_str.return_value = "2026-01-01"
    mock_pipeline.run_pipeline.side_effect = RuntimeError("boom")

    exit_code = cli._cmd_summarize(_args(dry_run=True))

    assert exit_code == 1
    mock_send.assert_not_called()


@patch(f"{_MODULE}.send_telegram")
@patch(f"{_MODULE}.configure_logging")
@patch(f"{_MODULE}.pipeline")
@patch(f"{_MODULE}.get_settings")
def test_summarize_keyboard_interrupt_is_reported_like_an_error(
    mock_get_settings, mock_pipeline, mock_configure_logging, mock_send
):
    mock_get_settings.return_value = _make_settings()
    mock_configure_logging.return_value = None
    mock_pipeline.resolve_date_str.return_value = "2026-01-01"
    mock_pipeline.run_pipeline.side_effect = KeyboardInterrupt()

    exit_code = cli._cmd_summarize(_args())

    assert exit_code == 1
    mock_send.assert_called_once()
    text = mock_send.call_args[0][1]
    assert "KeyboardInterrupt" in text


@patch(f"{_MODULE}.send_telegram")
@patch(f"{_MODULE}.configure_logging")
@patch(f"{_MODULE}.pipeline")
@patch(f"{_MODULE}.get_settings")
def test_summarize_error_message_truncated_to_300_chars(
    mock_get_settings, mock_pipeline, mock_configure_logging, mock_send
):
    mock_get_settings.return_value = _make_settings()
    mock_configure_logging.return_value = None
    mock_pipeline.resolve_date_str.return_value = "2026-01-01"
    mock_pipeline.run_pipeline.side_effect = RuntimeError("x" * 1000)

    cli._cmd_summarize(_args())

    text = mock_send.call_args[0][1]
    # message body itself is capped at 300 chars, regardless of the fixed prefix
    assert "x" * 300 in text
    assert "x" * 301 not in text
