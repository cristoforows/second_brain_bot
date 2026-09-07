from __future__ import annotations

from unittest.mock import MagicMock, patch

from second_brain.core.models import RunResult
from second_brain.main import run_pipeline


_MODULE = "second_brain.main"


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.google_service_refresh_token = "/fake/sa.json"
    settings.input_drive_folder_id = "input-folder"
    settings.output_drive_folder_id = "output-folder"
    settings.app_timezone = "Asia/Singapore"
    # Empty telegram config so _init_agent skips telegram setup and
    # send_notification short-circuits without an HTTP call.
    settings.telegram_outbound_url = ""
    settings.telegram_outbound_secret = ""
    settings.telegram_chat_id = ""
    return settings


@patch(f"{_MODULE}.run_agent_with_prompt")
@patch(f"{_MODULE}.run_agent")
@patch(f"{_MODULE}.build_agent")
@patch(f"{_MODULE}.create_llm")
@patch(f"{_MODULE}.init_tools")
@patch(f"{_MODULE}.DriveService")
@patch(f"{_MODULE}.get_settings")
def test_full_pipeline(
    mock_settings: MagicMock,
    mock_drive_cls: MagicMock,
    mock_init_tools: MagicMock,
    mock_create_llm: MagicMock,
    mock_build_agent: MagicMock,
    mock_run_agent: MagicMock,
    mock_run_agent_with_prompt: MagicMock,
    sample_dump_text: str,
) -> None:
    """Pipeline finds the dump file, parses messages, and invokes the agent."""
    mock_settings.return_value = _make_settings()

    drive = mock_drive_cls.return_value
    drive.find_file.return_value = {"id": "dump-id", "name": "2025-03-01"}
    drive.read_file_raw.return_value = sample_dump_text
    drive._updates = []
    drive._reads = []

    mock_run_agent.return_value = {"messages": ["done"]}

    result = run_pipeline(date_str="2025-03-01")

    # Verify the pipeline steps
    mock_drive_cls.assert_called_once_with("/fake/sa.json")
    mock_init_tools.assert_called_once_with(drive, "output-folder", dry_run=False)
    drive.find_file.assert_any_call("input-folder", "2025-03-01.md")
    drive.read_file_raw.assert_any_call("dump-id", "2025-03-01.md")
    mock_create_llm.assert_called_once()
    mock_build_agent.assert_called_once()
    mock_run_agent.assert_called_once()
    mock_run_agent_with_prompt.assert_not_called()

    # Verify 5 messages were parsed from sample dump
    agent_messages = mock_run_agent.call_args[0][1]
    assert len(agent_messages) == 5

    assert isinstance(result, RunResult)
    assert result.mode == "messages"
    assert result.message_count == 5
    assert result.date == "2025-03-01"
    assert result.duration_s >= 0


@patch(f"{_MODULE}.run_agent_with_prompt")
@patch(f"{_MODULE}.run_agent")
@patch(f"{_MODULE}.build_agent")
@patch(f"{_MODULE}.create_llm")
@patch(f"{_MODULE}.init_tools")
@patch(f"{_MODULE}.DriveService")
@patch(f"{_MODULE}.get_settings")
def test_pipeline_no_dump_file(
    mock_settings: MagicMock,
    mock_drive_cls: MagicMock,
    mock_init_tools: MagicMock,
    mock_create_llm: MagicMock,
    mock_build_agent: MagicMock,
    mock_run_agent: MagicMock,
    mock_run_agent_with_prompt: MagicMock,
) -> None:
    """When no dump file exists, the pipeline runs to-do maintenance instead."""
    mock_settings.return_value = _make_settings()

    drive = mock_drive_cls.return_value
    drive.find_file.return_value = None
    drive._updates = []
    drive._reads = []

    result = run_pipeline(date_str="2025-03-01")

    # Agent is still built, but invoked via the maintenance prompt path.
    mock_create_llm.assert_called_once()
    mock_build_agent.assert_called_once()
    mock_run_agent.assert_not_called()
    mock_run_agent_with_prompt.assert_called_once()

    assert result.mode == "todo_maintenance"
    assert result.message_count == 0
    assert result.date == "2025-03-01"


@patch(f"{_MODULE}.run_agent_with_prompt")
@patch(f"{_MODULE}.run_agent")
@patch(f"{_MODULE}.build_agent")
@patch(f"{_MODULE}.create_llm")
@patch(f"{_MODULE}.init_tools")
@patch(f"{_MODULE}.DriveService")
@patch(f"{_MODULE}.get_settings")
def test_pipeline_empty_dump_file(
    mock_settings: MagicMock,
    mock_drive_cls: MagicMock,
    mock_init_tools: MagicMock,
    mock_create_llm: MagicMock,
    mock_build_agent: MagicMock,
    mock_run_agent: MagicMock,
    mock_run_agent_with_prompt: MagicMock,
) -> None:
    """A dump file with no parseable messages still triggers to-do maintenance."""
    mock_settings.return_value = _make_settings()

    drive = mock_drive_cls.return_value
    drive.find_file.return_value = {"id": "dump-id", "name": "2025-03-01"}
    drive.read_file_raw.return_value = "No delimiters here, just plain text."
    drive._updates = []
    drive._reads = []

    result = run_pipeline(date_str="2025-03-01")

    mock_run_agent.assert_not_called()
    mock_run_agent_with_prompt.assert_called_once()

    assert result.mode == "todo_maintenance"
    assert result.message_count == 0


@patch(f"{_MODULE}.run_agent_with_prompt")
@patch(f"{_MODULE}.run_agent")
@patch(f"{_MODULE}.build_agent")
@patch(f"{_MODULE}.create_llm")
@patch(f"{_MODULE}.init_tools")
@patch(f"{_MODULE}.DriveService")
@patch(f"{_MODULE}.get_settings")
def test_pipeline_notify_receives_summary_then_todos_in_order(
    mock_settings: MagicMock,
    mock_drive_cls: MagicMock,
    mock_init_tools: MagicMock,
    mock_create_llm: MagicMock,
    mock_build_agent: MagicMock,
    mock_run_agent: MagicMock,
    mock_run_agent_with_prompt: MagicMock,
    sample_dump_text: str,
) -> None:
    """A provided `notify` callback receives exactly the run summary, then the
    active to-do list, in that order — instead of the pipeline sending
    Telegram messages directly."""
    mock_settings.return_value = _make_settings()

    drive = mock_drive_cls.return_value
    drive._updates = []
    drive._reads = []

    def find_file_side_effect(folder_id: str, name: str):
        if name == "2025-03-01.md":
            return {"id": "dump-id", "name": name}
        if name == "to-do":
            return {"id": "todo-folder-id", "name": "to-do"}
        if name == "to-do.md":
            return {"id": "todo-file-id", "name": "to-do.md"}
        return None

    drive.find_file.side_effect = find_file_side_effect

    def read_file_raw_side_effect(file_id: str, display_path: str) -> str:
        if file_id == "dump-id":
            return sample_dump_text
        if file_id == "todo-file-id":
            return "- [ ] Buy milk\n- [ ] Call the plumber\n"
        return ""

    drive.read_file_raw.side_effect = read_file_raw_side_effect

    notified: list[str] = []
    result = run_pipeline(date_str="2025-03-01", notify=notified.append)

    assert len(notified) == 2
    assert "2025-03-01" in notified[0]
    assert "5 message" in notified[0]
    assert "Buy milk" in notified[1]
    assert "Call the plumber" in notified[1]

    assert result.mode == "messages"
    assert result.message_count == 5
