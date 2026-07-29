from langchain_core.messages import AIMessage

import drive_handler
from vault_agent import SearchAgentError, _build_tools, run_agent

_MAX_FILE_CHARS = 6000


class FakeToolLLM:
    """Replays each queued AIMessage in turn; raising entries are exceptions."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.bound_tools = None
        self.invoke_count = 0

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        self.invoke_count += 1
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _tool_call(name, **args):
    return {"name": name, "args": args, "id": f"call-{name}"}


# --- run_agent ---


def test_run_agent_walks_tree_then_returns_final_answer(monkeypatch):
    monkeypatch.setattr(
        drive_handler,
        "list_folder_contents",
        lambda service, folder_id: [{"id": "f1", "name": "Directory.yaml", "mimeType": "text/yaml"}],
    )
    monkeypatch.setattr(
        drive_handler, "read_file", lambda service, file_id: "children:\n  - Areas/health.md"
    )

    llm = FakeToolLLM(
        AIMessage(content="", tool_calls=[_tool_call("list_folder", folder_id="root")]),
        AIMessage(content="", tool_calls=[_tool_call("read_file", file_id="f1")]),
        AIMessage(content="Found it in Areas/health.md: dentist appointment next week."),
    )

    result = run_agent(llm, "svc", "root", "dentist")

    assert result == "Found it in Areas/health.md: dentist appointment next week."
    assert {t.name for t in llm.bound_tools} == {"list_folder", "read_file"}


def test_run_agent_reports_no_match_without_fabricating(monkeypatch):
    monkeypatch.setattr(drive_handler, "list_folder_contents", lambda service, folder_id: [])
    llm = FakeToolLLM(AIMessage(content='No mention of "passport" found in the vault.'))

    result = run_agent(llm, "svc", "root", "passport")

    assert "No mention" in result


def test_run_agent_raises_search_agent_error_on_llm_failure():
    llm = FakeToolLLM(RuntimeError("openrouter 500"))

    try:
        run_agent(llm, "svc", "root", "dentist")
        assert False, "expected SearchAgentError"
    except SearchAgentError as e:
        assert "openrouter 500" in str(e)


def test_run_agent_gives_up_after_max_steps_instead_of_looping_forever(monkeypatch):
    monkeypatch.setattr(drive_handler, "list_folder_contents", lambda service, folder_id: [])

    # Always asks for another tool call — the loop must still terminate.
    responses = [
        AIMessage(content="", tool_calls=[_tool_call("list_folder", folder_id="root")])
        for _ in range(20)
    ]
    llm = FakeToolLLM(*responses)

    result = run_agent(llm, "svc", "root", "dentist")

    assert "too many steps" in result
    assert llm.invoke_count == 12  # _MAX_STEPS


# --- _build_tools ---


def test_list_folder_tool_tags_files_and_folders(monkeypatch):
    monkeypatch.setattr(
        drive_handler,
        "list_folder_contents",
        lambda service, folder_id: [
            {"id": "1", "name": "Projects", "mimeType": drive_handler.FOLDER_MIME_TYPE},
            {"id": "2", "name": "Directory.yaml", "mimeType": "text/yaml"},
        ],
    )
    tools = {t.name: t for t in _build_tools("svc")}

    out = tools["list_folder"].invoke({"folder_id": "root"})

    assert "[FOLDER] Projects (id: 1)" in out
    assert "[FILE] Directory.yaml (id: 2)" in out


def test_list_folder_tool_reports_empty_folder(monkeypatch):
    monkeypatch.setattr(drive_handler, "list_folder_contents", lambda service, folder_id: [])
    tools = {t.name: t for t in _build_tools("svc")}

    out = tools["list_folder"].invoke({"folder_id": "empty"})

    assert "empty" in out.lower()


def test_read_file_tool_truncates_long_content(monkeypatch):
    monkeypatch.setattr(drive_handler, "read_file", lambda service, file_id: "x" * (_MAX_FILE_CHARS + 500))
    tools = {t.name: t for t in _build_tools("svc")}

    out = tools["read_file"].invoke({"file_id": "big"})

    assert out.endswith("…(truncated)")
    assert len(out) <= _MAX_FILE_CHARS + len("\n…(truncated)")


def test_read_file_tool_reports_unreadable_file(monkeypatch):
    monkeypatch.setattr(drive_handler, "read_file", lambda service, file_id: None)
    tools = {t.name: t for t in _build_tools("svc")}

    out = tools["read_file"].invoke({"file_id": "missing"})

    assert "could not read" in out.lower()
