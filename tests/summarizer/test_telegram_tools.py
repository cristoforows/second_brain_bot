from __future__ import annotations

from unittest.mock import patch

import pytest

from second_brain.summarizer.tools import telegram_tools
from second_brain.summarizer.tools.telegram_tools import send_telegram_message


@pytest.fixture(autouse=True)
def _reset_telegram_tools():
    yield
    telegram_tools.init_tools("", dry_run=False)


def test_get_all_tools_empty_when_no_default_chat_id():
    telegram_tools.init_tools("", dry_run=False)
    assert telegram_tools.get_all_tools() == []


def test_get_all_tools_returns_tool_when_configured():
    telegram_tools.init_tools("chat-1", dry_run=False)
    assert telegram_tools.get_all_tools() == [send_telegram_message]


@patch("second_brain.summarizer.tools.telegram_tools.send_telegram")
def test_send_notification_calls_core_notify(mock_send):
    telegram_tools.init_tools("chat-1", dry_run=False)
    telegram_tools.send_notification("hello")
    mock_send.assert_called_once_with("chat-1", "hello")


@patch("second_brain.summarizer.tools.telegram_tools.send_telegram")
def test_send_notification_skipped_without_default_chat_id(mock_send):
    telegram_tools.init_tools("", dry_run=False)
    telegram_tools.send_notification("hello")
    mock_send.assert_not_called()


@patch("second_brain.summarizer.tools.telegram_tools.send_telegram")
def test_send_notification_dry_run_skips_send(mock_send):
    telegram_tools.init_tools("chat-1", dry_run=True)
    telegram_tools.send_notification("hello")
    mock_send.assert_not_called()


@patch("second_brain.summarizer.tools.telegram_tools.send_telegram")
def test_send_telegram_message_tool_uses_default_chat_id(mock_send):
    telegram_tools.init_tools("chat-1", dry_run=False)
    result = send_telegram_message.invoke({"text": "hi there"})
    mock_send.assert_called_once_with("chat-1", "hi there")
    assert "chat-1" in result


@patch("second_brain.summarizer.tools.telegram_tools.send_telegram")
def test_send_telegram_message_tool_dry_run_skips_send(mock_send):
    telegram_tools.init_tools("chat-1", dry_run=True)
    result = send_telegram_message.invoke({"text": "hi there"})
    mock_send.assert_not_called()
    assert "[dry-run]" in result


def test_send_telegram_message_tool_errors_without_chat_id():
    telegram_tools.init_tools("", dry_run=False)
    result = send_telegram_message.invoke({"text": "hi there"})
    assert "No chat_id" in result
