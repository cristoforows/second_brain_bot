"""Timebox scheduling: target-date computation, LLM generation, rendering.

All judgment lives here behind a small interface; the Telegram handler is
thin glue. The LLM client is injected so everything is testable offline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_MAX_ATTEMPTS = 2  # one automatic retry

Mode = Literal["office", "wfh", "nonworking"]


@dataclass(frozen=True)
class DayConfig:
    """Fixed daily anchors handed to the planner as overridable defaults.

    Times are HH:MM (24h); durations are minutes. The LLM owns placement and
    may override any of these when a user task clearly states a different time.
    The work window (work_start/work_end/work_end_hard) only applies on working
    days (office/wfh); it is ignored on non-working days.
    """

    day_start: str
    day_end: str
    lunch: str
    dinner: str
    eat_duration_min: int
    commute_morning: str
    commute_evening: str
    commute_duration_min: int
    work_start: str
    work_end: str
    work_end_hard: str


# The prompt is expected to be tuned after a few days of real use — keep it here.
_SYSTEM_PROMPT = """\
You are a meticulous personal day planner. Build a timeboxed schedule for \
{target_date} ({weekday}). The user is in "{mode}" mode today.

You receive the user's tasks verbatim, one per line, in the order they were sent.

Fixed daily blocks (defaults — treat each as a normal slot in your output):
- The day runs {day_start} to {day_end}. Place everything inside this window \
unless a task explicitly states otherwise (e.g. "start my day at 7").
- Lunch at {lunch} for {eat_duration} minutes (task name: "Lunch").
- Dinner at {dinner} for {eat_duration} minutes (task name: "Dinner").
{commute_block}

Rules:
- Emit the fixed blocks above as their own slots. BUT if a user task clearly \
occupies one of those times (e.g. "lunch meeting at 12:30"), replace that block \
with the user's task instead of emitting both.
- A task may include a duration (e.g. "90m", "2h") and/or freeform constraints \
(e.g. "morning", "after 6pm"). Honor them exactly.
- Estimate a sensible duration for any task that has none.
- Time slots must not overlap. Short breathing gaps between tasks are fine.
- Use 24-hour HH:MM times.
{workday_rules}\
- If everything cannot fit in the day, drop the least important / least \
time-pressured tasks until the plan fits. Report every dropped task with a \
one-line reason. Never ask the user questions.
"""

# Working-day boundaries + focus-slot filling. Injected for office/wfh only;
# non-working days get an empty string here.
_WORKDAY_RULES = """\
- Classify each task as work (job/professional) or non-work (personal, errands, \
leisure) by inferring from its wording.
- Work tasks belong in the work window {work_start}-{work_end}. You may extend \
to {work_end_hard} only when necessary, but avoid the {work_end}-{work_end_hard} \
hour when you can. Never schedule work past {work_end_hard}; if work tasks cannot \
fit by {work_end_hard}, drop the least important and report them.
- Non-work tasks may take at most 60 minutes TOTAL inside the work window \
{work_start}-{work_end}; schedule any remaining non-work tasks after {work_end}.
- Leave no empty stretches in the day — fill every gap with placeholder focus \
slots the user decides on the day itself:
  - Between {work_start} and {work_end}, fill gaps with 90-minute "Work Focus" \
slots separated by 15-minute "Break" slots.
  - Between {work_end} and 23:30, fill gaps with 90-minute "Personal Focus" \
slots separated by 15-minute "Break" slots.
  Keep these focus slots even when there is nothing else to schedule. Never \
create a focus slot after 23:30.
"""

_COMMUTE_OFFICE = (
    "- Morning commute at {commute_morning} for {commute_duration} minutes "
    '(task name: "Commute").\n'
    "- Evening commute at {commute_evening} for {commute_duration} minutes "
    '(task name: "Commute").'
)
_MODE_BLOCK = {
    "office": _COMMUTE_OFFICE,
    "wfh": "- Working from home today: no commute blocks.",
    "nonworking": "- Non-working day (day off): no commute blocks.",
}


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


class ScheduleGenerationError(Exception):
    """The LLM failed to produce a valid schedule after the automatic retry.

    The caller should keep the task buffer so the user can retry /done."""


def _build_system_prompt(target_date: date, day: DayConfig, mode: Mode) -> str:
    """Render the planner system prompt for the given day config and mode."""
    commute_block = _MODE_BLOCK[mode].format(
        commute_morning=day.commute_morning,
        commute_evening=day.commute_evening,
        commute_duration=day.commute_duration_min,
    )
    # Work-window boundaries and focus filling apply on working days only.
    if mode == "nonworking":
        workday_rules = ""
    else:
        workday_rules = _WORKDAY_RULES.format(
            work_start=day.work_start,
            work_end=day.work_end,
            work_end_hard=day.work_end_hard,
        )
    return _SYSTEM_PROMPT.format(
        target_date=target_date.isoformat(),
        weekday=target_date.strftime("%A"),
        mode=mode,
        day_start=day.day_start,
        day_end=day.day_end,
        lunch=day.lunch,
        dinner=day.dinner,
        eat_duration=day.eat_duration_min,
        commute_block=commute_block,
        workday_rules=workday_rules,
    )


def generate_schedule(
    tasks: list[str], target_date: date, llm, day: DayConfig, mode: Mode
) -> TimeboxResult:
    """Turn raw task messages into a structured timeboxed plan via the LLM.

    Fixed daily blocks (lunch/dinner/commute, bounded by the day window) are
    passed as overridable defaults; commute blocks are only included in office
    mode. Retries once on API errors or invalid structured output; raises
    ScheduleGenerationError after the second failure."""
    structured_llm = llm.with_structured_output(TimeboxResult)
    system = _build_system_prompt(target_date, day, mode)
    messages = [("system", system), ("human", "\n".join(tasks))]

    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            result = structured_llm.invoke(messages)
            if result is None:
                # with_structured_output returns None when parsing fails silently
                raise ValueError("structured output could not be parsed")
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"Schedule generation attempt {attempt} failed: {e}")
    raise ScheduleGenerationError(
        f"schedule generation failed after {_MAX_ATTEMPTS} attempts"
    ) from last_error


def render_schedule(result: TimeboxResult, target_date: date) -> str:
    """Format a structured result as the Telegram reply text."""
    lines = [f"Timebox for {target_date.strftime('%A, %d %b %Y')}", ""]
    for item in result.schedule:
        line = f"{item.start}-{item.end}  {item.task}"
        if item.note:
            line += f" ({item.note})"
        lines.append(line)
    lines.extend(dropped_notice_lines(result))
    return "\n".join(lines)


def dropped_notice_lines(result: TimeboxResult) -> list[str]:
    """Render the shared 'couldn't be scheduled' notice, or nothing if all fit."""
    if not result.dropped:
        return []
    n = len(result.dropped)
    lines = ["", f"⚠️ {n} task(s) couldn't be scheduled (ran out of time):"]
    for item in result.dropped:
        lines.append(f"- {item.task} — {item.reason}")
    return lines
