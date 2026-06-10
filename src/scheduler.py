"""Timebox scheduling: target-date computation, LLM generation, rendering.

All judgment lives here behind a small interface; the Telegram handler is
thin glue. The LLM client is injected so everything is testable offline.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_WINDOW_START = "09:00"
DEFAULT_WINDOW_END = "22:00"

# The prompt is expected to be tuned after a few days of real use — keep it here.
_SYSTEM_PROMPT = """\
You are a meticulous personal day planner. Build a timeboxed schedule for \
{target_date} ({weekday}).

You receive the user's tasks verbatim, one per line, in the order they were sent.

Rules:
- A task may include a duration (e.g. "90m", "2h") and/or freeform constraints \
(e.g. "morning", "after 6pm"). Honor them exactly.
- Estimate a sensible duration for any task that has none.
- Place every task within the waking window {window_start}-{window_end}. If the \
user explicitly states a different window in a task (e.g. "start my day at 7"), \
honor their window instead.
- Time slots must not overlap. Short breathing gaps between tasks are fine.
- If everything cannot fit in the day, drop the least important / least \
time-pressured tasks until the plan fits. Report every dropped task with a \
one-line reason. Never ask the user questions.
- Use 24-hour HH:MM times.
"""


class ScheduleItem(BaseModel):
    start: str = Field(description="Slot start time, 24h HH:MM")
    end: str = Field(description="Slot end time, 24h HH:MM")
    task: str = Field(description="Short task name")
    note: str | None = Field(default=None, description="Optional scheduling note")


class DroppedTask(BaseModel):
    task: str = Field(description="The task that was cut from the plan")
    reason: str = Field(description="One-line reason it was dropped")


class TimeboxResult(BaseModel):
    schedule: list[ScheduleItem] = Field(description="Non-overlapping timeboxed plan")
    dropped: list[DroppedTask] = Field(
        default_factory=list, description="Tasks that did not fit, with reasons"
    )


def compute_target_date(now: datetime, timezone_name: str, cutoff_hour: int) -> date:
    """Return the date being planned: tomorrow in the given timezone, or the
    current day when local time is strictly before the late-night cutoff hour."""
    local = now.astimezone(ZoneInfo(timezone_name))
    if local.hour < cutoff_hour:
        return local.date()
    return local.date() + timedelta(days=1)


def create_llm(api_key: str, model: str) -> ChatOpenAI:
    """Create a ChatOpenAI client pointed at OpenRouter."""
    return ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        openai_api_base=_OPENROUTER_BASE_URL,
        extra_body={"include_reasoning": False},
        request_timeout=120,
    )


def generate_schedule(tasks: list[str], target_date: date, llm) -> TimeboxResult:
    """Turn raw task messages into a structured timeboxed plan via the LLM."""
    structured_llm = llm.with_structured_output(TimeboxResult)
    system = _SYSTEM_PROMPT.format(
        target_date=target_date.isoformat(),
        weekday=target_date.strftime("%A"),
        window_start=DEFAULT_WINDOW_START,
        window_end=DEFAULT_WINDOW_END,
    )
    return structured_llm.invoke([("system", system), ("human", "\n".join(tasks))])


def render_schedule(result: TimeboxResult, target_date: date) -> str:
    """Format a structured result as the Telegram reply text."""
    lines = [f"Timebox for {target_date.strftime('%A, %d %b %Y')}", ""]
    for item in result.schedule:
        line = f"{item.start}-{item.end}  {item.task}"
        if item.note:
            line += f" ({item.note})"
        lines.append(line)
    if result.dropped:
        lines.append("")
        lines.append("Dropped:")
        for item in result.dropped:
            lines.append(f"- {item.task} — {item.reason}")
    return "\n".join(lines)
