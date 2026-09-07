from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from second_brain.bot.timebox_planner import (
    DayConfig,
    DroppedTask,
    ScheduleItem,
    ScheduleGenerationError,
    TimeboxResult,
    compute_target_date,
    generate_schedule,
    render_schedule,
)

SG = "Asia/Singapore"  # UTC+8, no DST

DAY = DayConfig(
    day_start="09:00",
    day_end="22:00",
    lunch="12:30",
    dinner="19:00",
    eat_duration_min=60,
    commute_morning="08:00",
    commute_evening="18:00",
    commute_duration_min=45,
    work_start="09:00",
    work_end="17:00",
    work_end_hard="18:00",
)


class FakeStructuredLLM:
    """Returns each queued outcome in turn; raising ones are Exception instances."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeLLM:
    def __init__(self, *outcomes):
        self.structured = FakeStructuredLLM(*outcomes)
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self.structured


# --- compute_target_date ---


def test_evening_session_plans_tomorrow():
    # 23:30 SG on Jun 11 (= 15:30 UTC)
    now = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)
    assert compute_target_date(now, SG, 3) == date(2026, 6, 12)


def test_late_night_session_plans_current_day():
    # 01:30 SG on Jun 12 (= 17:30 UTC Jun 11)
    now = datetime(2026, 6, 11, 17, 30, tzinfo=timezone.utc)
    assert compute_target_date(now, SG, 3) == date(2026, 6, 12)


def test_cutoff_hour_itself_plans_tomorrow():
    # exactly 03:00 SG on Jun 12 — hours *strictly below* the cutoff plan today
    now = datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc)
    assert compute_target_date(now, SG, 3) == date(2026, 6, 13)


def test_local_day_wins_when_utc_disagrees():
    # 17:00 UTC Jun 11 is already 01:00 Jun 12 in SG. With cutoff 0 (never plan
    # "today"), tomorrow must be SG-tomorrow (Jun 13), not UTC-tomorrow (Jun 12).
    now = datetime(2026, 6, 11, 17, 0, tzinfo=timezone.utc)
    assert compute_target_date(now, SG, 0) == date(2026, 6, 13)


def test_now_already_in_local_zone_works_too():
    # midday SG time passed as an SG-aware datetime, cutoff 3 -> tomorrow
    now = datetime(2026, 6, 11, 12, 0, tzinfo=ZoneInfo(SG))
    assert compute_target_date(now, SG, 3) == date(2026, 6, 12)


# --- render_schedule ---


def _result(dropped=()):
    return TimeboxResult(
        schedule=[
            ScheduleItem(start="09:00", end="10:30", task="deep work on report", note="hardest first"),
            ScheduleItem(start="10:45", end="11:00", task="wash dishes"),
        ],
        dropped=list(dropped),
    )


def test_render_lists_slots_for_target_date():
    text = render_schedule(_result(), date(2026, 6, 12))
    assert "Friday" in text and "12 Jun 2026" in text
    assert "09:00-10:30  deep work on report (hardest first)" in text
    assert "10:45-11:00  wash dishes" in text


def test_render_includes_dropped_section_with_reasons():
    text = render_schedule(
        _result(dropped=[DroppedTask(task="organize garage", reason="no time left in the day")]),
        date(2026, 6, 12),
    )
    assert "couldn't be scheduled" in text
    assert "organize garage" in text and "no time left in the day" in text


def test_render_omits_dropped_section_when_empty():
    text = render_schedule(_result(), date(2026, 6, 12))
    assert "Dropped" not in text


# --- generate_schedule ---


def test_generate_returns_structured_result_from_llm():
    canned = _result()
    llm = FakeLLM(canned)
    out = generate_schedule(
        ["wash dishes", "deep work 90m, morning"], date(2026, 6, 12), llm, DAY, "wfh"
    )
    assert out is canned
    assert llm.schema is TimeboxResult


def test_generate_sends_tasks_verbatim_with_target_date_and_window():
    llm = FakeLLM(_result())
    generate_schedule(["wash dishes", "call mom after 6pm"], date(2026, 6, 12), llm, DAY, "wfh")
    system_text = llm.structured.messages[0][1]
    human_text = llm.structured.messages[1][1]
    assert "2026-06-12" in system_text
    assert "09:00" in system_text and "22:00" in system_text
    assert human_text == "wash dishes\ncall mom after 6pm"


def test_office_mode_injects_commute_blocks_and_anchors():
    llm = FakeLLM(_result())
    generate_schedule(["gym"], date(2026, 6, 12), llm, DAY, "office")
    system_text = llm.structured.messages[0][1]
    assert 'office' in system_text
    assert "08:00" in system_text and "18:00" in system_text  # commute anchors
    assert "45 minutes" in system_text  # commute duration
    assert "12:30" in system_text and "19:00" in system_text  # lunch / dinner


def test_wfh_mode_omits_commute_blocks():
    llm = FakeLLM(_result())
    generate_schedule(["gym"], date(2026, 6, 12), llm, DAY, "wfh")
    system_text = llm.structured.messages[0][1]
    assert "no commute" in system_text.lower()
    # morning commute anchor absent (18:00 now legitimately appears as the work
    # window's hard end)
    assert "08:00" not in system_text


def test_working_modes_include_work_window_and_focus_rules():
    llm = FakeLLM(_result())
    generate_schedule(["email"], date(2026, 6, 12), llm, DAY, "wfh")
    system_text = llm.structured.messages[0][1]
    assert "Work Focus" in system_text and "Personal Focus" in system_text
    assert "17:00" in system_text  # work-window soft end


def test_nonworking_mode_omits_work_window_and_commute():
    llm = FakeLLM(_result())
    generate_schedule(["read a book"], date(2026, 6, 12), llm, DAY, "nonworking")
    system_text = llm.structured.messages[0][1]
    assert "Non-working day" in system_text
    assert "Work Focus" not in system_text
    assert "17:00" not in system_text  # work window not injected


def test_single_failure_is_retried_transparently():
    canned = _result()
    llm = FakeLLM(RuntimeError("api hiccup"), canned)
    assert generate_schedule(["wash dishes"], date(2026, 6, 12), llm, DAY, "wfh") is canned


def test_unparseable_output_counts_as_failure_and_is_retried():
    canned = _result()
    llm = FakeLLM(None, canned)  # with_structured_output yields None on parse failure
    assert generate_schedule(["wash dishes"], date(2026, 6, 12), llm, DAY, "wfh") is canned


def test_double_failure_raises_and_same_tasks_can_be_retried():
    tasks = ["wash dishes", "gym 1h"]
    failing = FakeLLM(RuntimeError("down"), RuntimeError("still down"))
    with pytest.raises(ScheduleGenerationError):
        generate_schedule(tasks, date(2026, 6, 12), failing, DAY, "wfh")

    # caller re-invokes with the identical task list and now succeeds
    canned = _result()
    recovered = FakeLLM(canned)
    assert generate_schedule(tasks, date(2026, 6, 12), recovered, DAY, "wfh") is canned
    assert recovered.structured.messages[1][1] == "wash dishes\ngym 1h"
