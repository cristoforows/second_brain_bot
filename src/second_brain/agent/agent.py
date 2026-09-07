from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from second_brain.agent.prompts import AD_HOC_PROMPT, build_index_prompt, build_system_prompt
from second_brain.core.models import Message

log = structlog.get_logger()


def build_agent(llm: ChatOpenAI, tools: list) -> Any:
    """Construct a LangGraph ReAct agent wired with the given LLM and tools.

    The system prompt is injected at invocation time (not at build time)
    because it includes the batch of messages to process.
    """
    return create_react_agent(model=llm, tools=tools)


def run_agent_with_prompt(agent: Any, prompt: str) -> dict:
    """Invoke the agent with a raw user prompt string.

    Useful for ad-hoc queries like "list all existing projects".
    """
    log.info("agent_invocation_start")

    result = agent.invoke(
        {
            "messages": [
                {"role": "system", "content": AD_HOC_PROMPT},
                {"role": "user", "content": prompt},
            ]
        },
        config={"recursion_limit": 100},
    )

    _log_agent_steps(result)
    log.info("agent_invocation_complete")

    final = result.get("messages", [])[-1]
    content = getattr(final, "content", "")
    if content:
        print(content)

    return result


def run_agent_index(agent: Any, changed_files: list[str] | None = None) -> dict:
    """Invoke the agent to rebuild Directory.yaml files across the knowledge base.

    Args:
        changed_files: Optional list of slash-separated file paths that were
            recently added or modified (e.g. ["projects/job-search/Job Search.md"]).
            When provided, the agent focuses on updating Directory.yaml files
            along those paths rather than doing a full crawl.
    """
    system_prompt = build_index_prompt(changed_files)
    log.info("agent_index_start", changed_files=changed_files or [])

    result = agent.invoke(
        {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Index the knowledge base now."},
            ]
        },
        config={"recursion_limit": 100},
    )

    _log_agent_steps(result)
    log.info("agent_index_complete")

    final = result.get("messages", [])[-1]
    content = getattr(final, "content", "")
    if content:
        print(content)

    return result


def run_agent(agent: Any, messages: list[Message]) -> dict:
    """Invoke the agent with a batch of parsed messages.

    Formats the messages into the system prompt and runs the agent loop
    until it finishes processing all messages.
    """
    messages_text = _format_messages(messages)
    system_prompt = build_system_prompt(messages_text)

    log.info("agent_invocation_start", message_count=len(messages))

    result = agent.invoke(
        {"messages": [{"role": "user", "content": system_prompt}]},
        config={"recursion_limit": 100},
    )

    _log_agent_steps(result)
    log.info("agent_invocation_complete", message_count=len(messages))
    return result


def _log_agent_steps(result: dict) -> None:
    """Log the agent's intermediate reasoning steps and tool interactions."""
    result_messages = result.get("messages", [])
    if not result_messages:
        return

    step = 0
    for msg in result_messages:
        if isinstance(msg, HumanMessage):
            continue

        if isinstance(msg, AIMessage):
            # Tool calls — the agent's decision to use a tool
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    step += 1
                    log.debug(
                        "agent_step",
                        step=step,
                        action="tool_call",
                        tool=tc.get("name"),
                        args=tc.get("args"),
                    )
            # Text content — the agent's reasoning or final response
            content = getattr(msg, "content", "")
            if content:
                step += 1
                log.debug(
                    "agent_step",
                    step=step,
                    action="thinking",
                    content=content[:500],
                )

        elif isinstance(msg, ToolMessage):
            step += 1
            content = getattr(msg, "content", "")
            log.debug(
                "agent_step",
                step=step,
                action="tool_result",
                tool=getattr(msg, "name", "unknown"),
                result=content[:500],
            )

def _format_messages(messages: list[Message]) -> str:
    """Format a list of Message objects into a readable text block for the prompt."""
    parts = []
    for msg in messages:
        parts.append(f"### Message [{msg.id}]\n{msg.content}")
    return "\n\n".join(parts)
