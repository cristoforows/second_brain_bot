from __future__ import annotations

from unittest.mock import MagicMock, patch

from second_brain.agent.agent import _format_messages, build_agent, run_agent
from second_brain.agent.llm import create_llm
from second_brain.agent.prompts import SYSTEM_PROMPT, build_system_prompt
from second_brain.core.config import Settings
from second_brain.core.models import Message


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_system_prompt_has_placeholder(self) -> None:
        assert "{messages}" in SYSTEM_PROMPT

    def test_build_system_prompt_injects_messages(self) -> None:
        result = build_system_prompt("Hello world")
        assert "Hello world" in result
        assert "{messages}" not in result

    def test_build_system_prompt_contains_workflow_steps(self) -> None:
        result = build_system_prompt("test")
        assert "read_directory_index" in result
        assert "write_to_category" in result
        assert "update_directory_index" in result


# ---------------------------------------------------------------------------
# LLM factory tests
# ---------------------------------------------------------------------------

class TestLLMFactory:
    def test_create_llm_returns_chat_openai(self) -> None:
        settings = Settings(
            openrouter_api_key="sk-test-key",
            llm={"model": "test/model", "temperature": 0.5, "max_tokens": 1024},
        )
        llm = create_llm(settings)
        assert llm.model_name == "test/model"
        assert llm.temperature == 0.5
        assert llm.max_tokens == 1024


# ---------------------------------------------------------------------------
# Message formatting tests
# ---------------------------------------------------------------------------

class TestFormatMessages:
    def test_formats_single_message(self) -> None:
        msgs = [Message(id="m1", content="Hello")]
        result = _format_messages(msgs)
        assert "### Message [m1]" in result
        assert "Hello" in result

    def test_formats_multiple_messages(self) -> None:
        msgs = [
            Message(id="m1", content="First"),
            Message(id="m2", content="Second"),
        ]
        result = _format_messages(msgs)
        assert "### Message [m1]" in result
        assert "### Message [m2]" in result
        assert "First" in result
        assert "Second" in result

    def test_empty_messages(self) -> None:
        assert _format_messages([]) == ""


# ---------------------------------------------------------------------------
# Agent build / run tests (mocked)
# ---------------------------------------------------------------------------

class TestBuildAgent:
    @patch("second_brain.agent.agent.create_react_agent")
    def test_build_agent_calls_create_react_agent(self, mock_create: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_tools = [MagicMock(), MagicMock()]
        mock_create.return_value = MagicMock()

        agent = build_agent(mock_llm, mock_tools)

        mock_create.assert_called_once_with(model=mock_llm, tools=mock_tools)
        assert agent is mock_create.return_value


class TestRunAgent:
    @patch("second_brain.agent.agent.create_react_agent")
    def test_run_agent_invokes_with_formatted_messages(self, mock_create: MagicMock) -> None:
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": ["done"]}

        messages = [
            Message(id="m1", content="Test message"),
        ]

        result = run_agent(mock_agent, messages)

        mock_agent.invoke.assert_called_once()
        call_args = mock_agent.invoke.call_args[0][0]
        assert "messages" in call_args
        user_content = call_args["messages"][0]["content"]
        assert "### Message [m1]" in user_content
        assert "Test message" in user_content
        assert result == {"messages": ["done"]}
