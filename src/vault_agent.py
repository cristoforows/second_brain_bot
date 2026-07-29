"""Agentic search over the user's knowledge vault in Google Drive.

The vault is an Obsidian vault (PARA + Zettelkasten hybrid) written by the
external second-brain service: a nested folder tree with a Directory.yaml
index per folder and notes cross-linked across folders. That shape can't be
substring-scanned like the bot's own flat inbox files — the LLM has to walk
the tree itself, so it gets two tools (list_folder, read_file) and navigates
via Directory.yaml and note links.

All judgment lives here behind a small interface; the Telegram handler
(search.py) is thin glue. The LLM client is injected so this is testable
offline, matching the pattern in scheduler.py.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

import drive_handler

logger = logging.getLogger(__name__)

_MAX_STEPS = 12          # tool-call round trips before giving up
_MAX_FILE_CHARS = 6000   # per-file read cap, keeps context/cost bounded

# The prompt is expected to be tuned after a few days of real use — keep it here.
_SYSTEM_PROMPT = """\
You are a search agent over the user's personal knowledge vault, stored in \
Google Drive as an Obsidian vault (PARA + Zettelkasten hybrid). You have two \
tools: `list_folder(folder_id)` lists a folder's direct children, and \
`read_file(file_id)` reads a file's text content.

Vault structure:
- The root folder contains AGENTS.md (global rules) and Directory.yaml (a \
top-level map).
- Five top-level folders organize by *actionability*, not topic:
  - To-Do/ — active daily tasks (single To-Do.md, with carry-over/archive rules)
  - Projects/ — time-bound work with a defined "done" state (one subfolder per \
project)
  - Areas/ — ongoing responsibilities with no end date (health, work, personal \
growth)
  - Resources/ — reference material and long-term notes, not tied to any \
active task
  - Archives/ — completed/inactive items moved out of the above
  - Media Resources/ — images/files referenced from notes elsewhere, not \
searchable text
- Every folder contains a Directory.yaml — a machine-readable index of that \
folder's children (name, path, type, status, one-line summary). This is your \
primary map: read a folder's Directory.yaml before listing/reading its \
contents, to know what's inside and whether it's still active.
- Some folders also contain an AGENTS.md with folder-specific editing rules — \
irrelevant to a read-only search, skip these.
- Notes cross-link each other via [Name](relative/path.md) links regardless of \
folder — the folder tells you *where* something lives (actionability), links \
tell you *how* it relates (context). A topic can span folders, so follow \
relevant links you find in notes rather than assuming everything on a subject \
sits in one folder.

Search algorithm:
1. list_folder the root, then read_file its Directory.yaml to see the \
top-level map.
2. Based on the query, drill into the relevant top-level folder: list_folder \
it, read its Directory.yaml, and use the `status` and `summary` fields to \
pick the right subfolder or file — skip anything marked archived/inactive \
unless the query is explicitly about history.
3. read_file the actual note(s) that look relevant.
4. Follow any [links](...) you find in those notes that look relevant to the \
query, and read those files too.
5. Stop once you have enough to answer, or after a reasonable number of \
steps — don't exhaustively read the whole vault.

When you're done, answer the user's query directly and concisely, in plain \
text suitable for a Telegram message. Cite the note file name(s) you drew \
from. If you found nothing relevant, say so plainly instead of guessing.
"""


class SearchAgentError(Exception):
    """The agent failed to produce an answer (LLM/API failure)."""


def _build_tools(service) -> list:
    @tool
    def list_folder(folder_id: str) -> str:
        """List the files and subfolders directly inside a Drive folder, given its id."""
        children = drive_handler.list_folder_contents(service, folder_id)
        if not children:
            return "(empty folder, or folder id not found)"
        lines = []
        for c in children:
            kind = "FOLDER" if c.get("mimeType") == drive_handler.FOLDER_MIME_TYPE else "FILE"
            lines.append(f"[{kind}] {c.get('name')} (id: {c.get('id')})")
        return "\n".join(lines)

    @tool
    def read_file(file_id: str) -> str:
        """Read a file's text content, given its id."""
        content = drive_handler.read_file(service, file_id)
        if content is None:
            return "(could not read file)"
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + "\n…(truncated)"
        return content

    return [list_folder, read_file]


def run_agent(llm, service, root_folder_id: str, query: str) -> str:
    """Run the tool-calling search loop; returns the agent's final answer text.

    Raises SearchAgentError if the LLM/API call itself fails. Exhausting the
    step budget without a final answer is not an error — it returns a message
    saying so, since the agent got *an* answer, just no confident one.
    """
    tools = _build_tools(service)
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f'User query: "{query}"\nVault root folder id: {root_folder_id}'),
    ]

    for _ in range(_MAX_STEPS):
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            raise SearchAgentError(str(e)) from e
        messages.append(response)

        if not response.tool_calls:
            return response.content

        for call in response.tool_calls:
            tool_fn = tools_by_name.get(call["name"])
            if tool_fn is None:
                result = f"error: unknown tool {call['name']}"
            else:
                try:
                    result = tool_fn.invoke(call["args"])
                except Exception as e:
                    result = f"error: {e}"
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    logger.warning(f"Search agent hit the {_MAX_STEPS}-step budget without a final answer")
    return "Search took too many steps without a clear answer — try a more specific query."
